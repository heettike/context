"""Reading and writing a file in one line, closed again: tests that leave files open bury real warnings."""
import json


def read(path, *mode, **how):
    with open(path, *mode, **how) as f:
        return f.read()


def lines(path, *mode, **how):
    with open(path, *mode, **how) as f:
        return f.readlines()


def write(data, path, mode="w", **how):
    with open(path, mode, **how) as f:
        return f.write(data)


def load(path, **how):
    with open(path, **how) as f:
        return json.load(f)


def dump(obj, path, **how):
    with open(path, "w") as f:
        json.dump(obj, f, **how)
