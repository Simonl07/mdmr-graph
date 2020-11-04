# MRSketch

Simple library for building multi-resolution sketches: Multi-level streaming statistics & Multi-level online machine learning

Supports arbitrary number of dimensions, levels of resolution, and node states

## Install
```
pip install mrsketch
```

## Quick Start

First, define the individual states that need to be stored at each resolution by specifying these functions to a state descriptor: 

Assuming we have a dataset/stream that contains [Year, Month, Day, Value] for each record

we want to keep track of the max value at each level of resolutions (year, month, and day levels)

```python
from mrsketch import Graph, StateDescriptor

max_state = StateDescriptor(
    constructor=lambda: [0],                                   # mutable list to keep track of max
    updater=lambda x, state: state[0] = max(state[0], x[3]),   # update the max by comparing with new record's value
    merger=lambda state1, state2: [max(state1[0] + state2[0])],# the max of two max as a new state
    serializer=lambda state: repr(state[0]),                   # python's repr
    deserializer=lambda x: [eval(x)],                          # reconstruct the state from input string
    extractor=lambda x: x[0]                                   # when get(), extract the max from the list (state)
)
```

Parameters | default | description | use case
--- | --- | --- | ---
constructor | Required | function that takes no input a return a newly initialized state | Used by the Graph to initalize new nodes
updater | Required | function that takes an input record, the state of a given node, and mutate the state with the input record | Used by the graph to update and populate effected nodes upon inserting a record
merger | Required | function that two input state and combined into a __new__ state | Used by the Graph to perform graph merges and aggregated queries
serializer | Required | function that takes a state as input and return the serialization of the given state as string, serializer and deserializer must be inverse functions | Used by the Graph to perform graph serialization
deserializer | Required | function that takes a string as input and return a deserialized state from the input, serializer and deserializer must be inverse functions | Used by the Graph to perform graph deserialization
extractor | lambda state: state | optional function that defines the behavior of state extraction on graph.get() | Used as the final stage of get(), once the states of relevant nodes are merged, extractor is applied on the final merged state to support custom extraction behavior. Default function is Identity, which returns the entire state obj. 

> Serializer and deserializer must be inverse functions: `deserializer(serializer(G)) == G`

Once the StateDescriptor is defined, pass it into the Graph constructor:

```python
g = Graph(
    state_descriptors={
        'max': max_state
    },
    path_extractor=lambda x: {
        'time': list(x[:3]),
    }
)
```

The path_extractor is a function that takes a record as input and returns a NDPath 

In this example the path along the `time` dimension is extracted by slicing the first three items in each record

This tells the graph how the hierarchical data can be extracted from a given record

now lets push some records into the graph:
```python
g.push([2020, 10, 30, 2])
g.push([2020, 10, 31, 2])
g.push([2020, 10, 31, 5])
g.push([2020, 11, 2, 10])
```

The graph will update the state of all nodes that are impacted by the dates. To extract, specify an NDPath
```python
g.get({'time': [2020, 10, 30]}) # -> 2
g.get({'time': [2020, 10]}) # -> 5
g.get({'time': [2020]}) # -> 10
```


## Design & Documentation

__Path__: Path represents a sequence of values along a specific hierarchical tree of resolution: Jun 16th, 2017 can be encoded as [2017,6,16], where indices encodes the level of hierarchy (2017 - top/root level, 16 - lowest/leaf level), and every next index is the child of (or nested in) the previous index. Geohash 8ygzq can be encoded as [8, y, g, z, q]


__NDPath__: N-dimensional path. A mapping of dimension names to __Path__.
A __Path__ only describes the path along a single dimension, the graph supports arbitrary number of multi-resolution dimensions:
```python
g = Graph(
    state_descriptors={
        'max': max_state
    },
    path_extractor=lambda x: {
        'time': list(x[:3]),
        'geohash': list(x[3:10]) # <- add arbitrary dimensions as long as its 
    }                             # hierarchy (path) can be extracted from the records
)
```

__Graph__: A Directed Acyclic Graph where node is identified by an NDPath describing its coordinates among N dimensions. The node manages arbitrary amount of states described by the graph state_descriptors. A node points to other child nodes with NDPath that overlapse with itself and extend by 1 level of resolution in any dimension. So `time=2018/1/1, geohash=abc` is a children of `time=2018/1, geohash=abc`, but not a children of `time=2019/1, geohash=abc`
