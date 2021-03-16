import wrapt

import my_gorilla
import inspect
import functools


def _update_wrapper_extended(wrapper, wrapped):
    updated_wrapper = functools.update_wrapper(wrapper, wrapped)
    try:
        updated_wrapper.__signature__ = inspect.signature(wrapped)
    except Exception:
        _logger.debug("Failed to restore original signature for wrapper around %s", wrapped)
    return updated_wrapper


def wrap_patch(destination, name, patch, settings=None):
    if settings is None:
        settings = my_gorilla.Settings(allow_hit=True, store_hit=True)

    original = getattr(destination, name)
    wrapped = _update_wrapper_extended(patch, original)

    patch = my_gorilla.Patch(destination, name, wrapped, settings=settings)
    my_gorilla.apply(patch)


class _SklearnTrainingSession(object):
    _session_stack = []

    def __init__(self, clazz, allow_children=True):
        self.allow_children = allow_children
        self.clazz = clazz
        self._parent = None

    def __enter__(self):
        if len(_SklearnTrainingSession._session_stack) > 0:
            self._parent = _SklearnTrainingSession._session_stack[-1]
            self.allow_children = (
                _SklearnTrainingSession._session_stack[-1].allow_children and self.allow_children
            )
        _SklearnTrainingSession._session_stack.append(self)
        return self

    def __exit__(self, tp, val, traceback):
        _SklearnTrainingSession._session_stack.pop()

    def should_log(self):
        return (self._parent is None) or (
            self._parent.allow_children and self._parent.clazz != self.clazz
        )


def create_patch_function(destination, function_name):
    def patch_function(self, *args, **kwargs):
        original = my_gorilla.get_original_attribute(destination, function_name)
        with _SklearnTrainingSession(clazz=self.__class__, allow_children=False) as sess:
            if sess.should_log():
                print(self, args, kwargs)
            return original(self, *args, **kwargs)

    return patch_function


@wrapt.when_imported("sklearn")
def setup_usage_logger_for_sklearn(sklearn):

    import sklearn

    for class_name, class_def in sklearn.utils.all_estimators():
        for function_name in ["fit", "fit_transform", "fit_predict"]:
            orig_func = getattr(class_def, function_name, None)
            if (not orig_func) or isinstance(orig_func, property):
                continue

            wrap_patch(class_def, function_name, create_patch_function(class_def, function_name))


def main():
    import mlflow
    from pprint import pprint
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import RandomForestRegressor

    mlflow.sklearn.autolog()

    X = np.array([[1, 1], [1, 2], [2, 2], [2, 3]])
    y = np.dot(X, np.array([1, 2])) + 3

    model = RandomForestRegressor()
    model.fit(X, y)


if __name__ == "__main__":
    main()
