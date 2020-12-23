import threading
import types
from copy import copy, deepcopy
from functools import reduce
import json
import pickle

supported_graph_serialization = {
    'json': json,
    'pickle': pickle
}


class StateDescriptor(object):

    def __init__(self, constructor, updater, merger, serializer, deserializer, extractor=lambda s: s):
        self.constructor = constructor
        self.updater = updater
        self.merger = merger
        self.serializer = serializer
        self.deserializer = deserializer
        self.extractor = extractor


class Path(object):
    '''
        Represents an immutable unbounded path (sequence of values) along certain dimension

        Keys (level-names) can be provided to each level for accessing by name
        Without names, levels can be accessed by index

        - Length of a path is the length of its sequence of values
        - Path1 is extendable_by Path2 if Path2 is longer than Path1
        - Path1.extend_by_one(Path2) returns a new Path where Path1
            is extended by one level towards Path2
    '''

    def __init__(self, values=tuple(), keys=tuple()):
        self.keys = keys
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        return self.values[self.keys.index(key) if key in self.keys else key]

    def subpath(self, i, j):
        return Path(self.values[i:j])

    def extendable_by(self, other):
        return len(other) > len(self)

    def extend_by_one(self, target):
        assert len(target) > len(self)
        return Path(self.values + [target.values[len(self)]])

    def pathstring(self):
        return '/' + '/'.join([str(v) for v in self.values])

    def __repr__(self):
        return f'Path(values={self.values}, keys={self.keys})'

    def __str__(self):
        return self.pathstring()

    def __hash__(self):
        return hash(self.pathstring())

    def __eq__(self, other):
        return all([self[i] == None or self[i] == other[i] for i in range(len(other))])


class NDPath(object):
    '''
        N-dimensional path is a mapping of keys (dimension names) to paths
    '''

    def __init__(self, paths):
        self.paths = paths

    def __len__(self):
        return sum([len(path) for path in self.paths.values()])

    def __getitem__(self, key):
        return self.paths[key]

    def __contains__(self, key):
        return key in self.paths

    def __iter__(self):
        return iter(self.paths)

    def items(self):
        return self.paths.items()

    def with_path(self, key, path):
        newpaths = self.paths.copy()
        newpaths[key] = path
        return NDPath(newpaths)

    def dimensions(self):
        return self.paths.keys()

    def extendable_by(self, other):
        return self.dimensions() == other.dimensions() and any([self[key].extendable_by(other[key]) for key in self.paths])

    def pathextend(self, other):
        if not self.extendable_by(other):
            raise BaseException(f'{self} is not extendable by {other}')
        return [self.with_path(key, path.extend_by_one(other[key])) for key, path in self.items() if path.extendable_by(other[key])]

    def __str__(self):
        output = ''
        for key in self:
            output += f'{key}={self[key]} '
        return output

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        return self.dimensions() == other.dimensions() and all([self[key] == other[key] for key in self])

    def __hash__(self):
        return hash(str(self))

    def to_hex(self):
        return pickle.dumps([(name, path) for name, path in self.paths.items()]).hex()

    def from_hex(hex):
        paths = {}
        for t in pickle.loads(bytes.fromhex(hex)):
            paths[t[0]] = t[1]
        return NDPath(paths)


class Graph(object):

    def __init__(self, state_descriptors, path_extractor):
        self.adjlist = {}
        self.path_extractor = lambda x: NDPath({
            key: Path(value)
            for key, value in path_extractor(x).items()
        })
        self.state_descriptors = state_descriptors
        self.lock = threading.Lock()
        self.size = 0

    def __newnode(self):
        node = types.SimpleNamespace()
        node.states = {name: descriptor.constructor() for name, descriptor in self.state_descriptors.items()}
        node.lock = threading.Lock()
        node.children = set()
        return node

    def push(self, record):
        target = self.path_extractor(record)
        visited = set()

        for dimension, path in target.items():
            root = NDPath({
                d: Path([]) if d != dimension else path.subpath(0,1)
                for d, p in target.items()
            })

            # Lock adjlist
            self.lock.acquire()
            if root not in self.adjlist:
                self.adjlist[root] = self.__newnode()
            self.lock.release()

            self.__insert(root, target, visited, record)

    def __insert(self, currpath, target, visited, record):
        # Put currpath in visited to prevent re-visits
        visited.add(currpath)

        node = self.adjlist[currpath]

        # Lock node & Update all states with record
        node.lock.acquire()
        for name, state in node.states.items():
            self.state_descriptors[name].updater(record, state)
        node.lock.release()

        if currpath.extendable_by(target):
            ndpaths = currpath.pathextend(target)
            for ndpath in ndpaths:

                # Lock adjlist for new nodes
                self.lock.acquire()
                if ndpath not in self.adjlist:
                    self.adjlist[ndpath] = self.__newnode()
                self.lock.release()

                # Lock node for modifying children
                node.lock.acquire()
                if ndpath not in node.children:
                    node.children.add(ndpath)
                node.lock.release()

                if ndpath not in visited:
                    self.__insert(ndpath, target, visited, record)

    def combinedstate(self, nodes):
        states = {}
        # group by states
        for node in nodes:
            # Lock nodes for state access
            node.lock.acquire()
            for name, state in node.states.items():
                if name not in states:
                    states[name] = []
                states[name].append(state)
            node.lock.release()

        # reduce by states
        # Note: At this point states can still be mutated
        for name, availiable_states in states.items():
            states[name] = self.state_descriptors[name].extractor(reduce(self.state_descriptors[name].merger, availiable_states))
        return states


    def get(self, ndpath):
        ndpath = NDPath({
            key: Path(value)
            for key, value in ndpath.items()
        })

        if len(ndpath) == 0:
            return self.combinedstate([node for ndpath, node in self.adjlist.items() if len(ndpath) == 1])

        if ndpath in self.adjlist:
            return [self.state_descriptors[name].extractor(state) for name, state in self.adjlist[ndpath].states.items()]

        return [sd.constructor() for sd in self.state_descriptors.values()]

    def edges(self):
        output = []
        for ndpath, node in self.adjlist.items():
            if len(node.children) == 0:
                output.append((str(ndpath), "None"))
            for children in node.children:
                output.append((str(ndpath), str(children)))
        return output

    def merge(self, other):
        # Lock the whole graph for state_descriptors updated
        self.lock.acquire()

        # Merge state descriptors
        for name, descriptor in other.state_descriptors.items():
            if name not in self.state_descriptors:
                self.state_descriptors[name] = descriptor

        self.lock.release()

        # Merge nodes
        for ndpath, node in other.adjlist.items():
            if ndpath not in self.adjlist:
                self.adjlist[ndpath] = self.__newnode()
                self.adjlist[ndpath].states = deepcopy(node.states)
                continue

            # If nodes with same ndpath exists, merge their states using merge function
            mystates = self.adjlist[ndpath].states
            otherstates = node.states
            for name, otherstate in otherstates.items():
                if name in mystates:
                    # --merge() must create a new state from the two instead of mutate
                    mystates[name] = self.state_descriptors[name].merger(mystates[name], otherstate)
                else:
                    mystates[name] = deepcopy(otherstate)


    def serialize(self, encoding='json'):
        if encoding not in supported_graph_serialization:
            raise BaseException(f'{encoding} is not a valid encoding option (options: json, pickle)')

        output = {}
        self.lock.acquire()
        for ndpath, node in self.adjlist.items():
            node.lock.acquire()
            encoded_node_states = {}
            for name, state in node.states.items():
                encoded_node_states[name] = self.state_descriptors[name].serializer(state)
            encoded_children = []
            for children in node.children:
                encoded_children.append(children.to_hex())
            node.lock.release()
            output[ndpath.to_hex()] = (encoded_node_states, encoded_children)
        self.lock.release()
        return supported_graph_serialization[encoding].dumps(output, indent=4)

    def from_serialization(self, bytes, encoding='json'):
        if encoding not in supported_graph_serialization:
            raise BaseException(f'{encoding} is not a valid encoding option (options: json, pickle)')

        tuple_dict = supported_graph_serialization[encoding].loads(bytes)
        self.lock.acquire()
        for ndpath_hex, encoded_node in tuple_dict.items():
            ndpath = NDPath.from_hex(ndpath_hex)
            self.adjlist[ndpath] = self.__newnode()
            self.adjlist[ndpath].lock.acquire()
            self.adjlist[ndpath].states = {
                name: self.state_descriptors[name].deserializer(encoded_state)
                for name, encoded_state in encoded_node[0].items()
            }
            self.adjlist[ndpath].children = [NDPath.from_hex(c) for c in encoded_node[1]]
            self.adjlist[ndpath].lock.release()
        self.lock.release()
