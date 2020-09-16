Pass `predict_func`

```python
def log_explanation(predict_func, features):
    explainer = shap.KernelExplainer(predict_func, **options)
    shap_values = explainer.shap_values(features)
    ...

mlflow.shap.log_explanation(regressor.predict, X)
mlflow.shap.log_explanation(classifier.predict_proba, X)

# when a model doesn't return a numpy array
def wrapper(model, features):
    def predict(features):
        return to_numpy_array(model.predict(features))
    return predict

mlflow.shap.log_explanation(wrapper(model), X)
```

- Seems inconvenient for a model that doesn't return a numpy array or pandas dataframe becaues the user needs to write a wrapper function.

Pass `explainer`.

```python
def log_explanation(explainer, data):
    shap_values = explainer.shap_values(data)
    ...


import shap

explainer = shap.TreeExplainer(model, **options)
mlflow.shap.log_explanation(explainer, X)
```

- Allow the user to choose an explainer.
- The user needs to create an explainer object.

Pass `model_uri`.

```python
def log_explanation(model_uri, data):
    model = mlflow.pyfunc.load_model(model_uri)
    explainer = shap.KernelExplainer(model.predict, ...)
    shap_values = explainer.shap_values(data)
    ...

with mlflow.start_run() as run:
    # log a model
    mlflow.sklearn.log_model(model, "model")
    model_uri = "runs:/{run_id}/model".format(run_id=run.info.run_id)

    # use the logged model
    mlflow.shap.log_explanation(model_uri, features)
```

- Seems inconvenient when the user just wants to log an explanation.
- We need extract design because `PyFuncModel` doesn't necessarily return probabilities.

```python
def log_explanation(any_ml_model, features):
    predict_func = magically_detect_predict_func(any_ml_model)
    explainer = shap.KernelExplainer(predict_func, **options)
    shap_values = explainer.shap_values(features)
    ...


mlflow.shap.log_explanation(any_ml_model, features)
```

- Ideal but definitely challenging
