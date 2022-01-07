from mlflow import pyfunc
from mlflow.pyfunc import scoring_server


app = scoring_server.init(pyfunc.load_pyfunc("/opt/ml/model/"))
