import mlflow
import fasttext
import fasttext_flavor

# How to prepare training data:
#
# $ wget https://dl.fbaipublicfiles.com/fasttext/data/cooking.stackexchange.tar.gz && tar xvzf cooking.stackexchange.tar.gz
# $ head -n 100 cooking.stackexchange.txt > cooking.train
#
# Reference: https://fasttext.cc/docs/en/supervised-tutorial.html#getting-and-preparing-the-data

model = fasttext.train_supervised(input="cooking.train")

artifact_path = "model"
with mlflow.start_run() as run:
    fasttext_flavor.log_model(model, artifact_path)

model_uri = "runs:/{}/{}".format(run.info.run_id, artifact_path)
loaded_model = fasttext_flavor.load_model(model_uri)

pred = model.predict(
    "Which baking dish is best to bake a banana bread ?"
)

print(pred)
