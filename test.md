# Finetune a text classification model

In this guide, we will show how to finetune a `DistilledBert` model to classify SMS as spam or not. We will also show how we can use MLFlow to track and monitor our finetuning. We will be using [Databricks Community Edition](https://community.cloud.databricks.com/) for visualization, it is completely free for use. If you haven't, you can register an account now via [link](https://www.databricks.com/try-databricks), or we will come back to it later.

We recommend turn on the free-tier GPU in Colab by **Edit -> notebook settings -> Hardware Accelerator**, it will significanly shorten the finetuning time.

## Install dependencies

We need `transformers`, `datasets` and `evaluate` package by Huggingface. Additionally, we install `mlflow` for tracking purpose.

```python
!pip install -q mlflow datasets evaluate transformers
```

We also need to update the `accelerate` package to be compatible with the training.

```python
!pip install -U -q accelerate
```

```python
# There is a strange pydantic issue, we can delete this in the future.
!pip install pydantic==1.10.12
```

Make sure you click on Runtime -> Restart runtime after installation to reflect the package change.

## Load the dataset

In this guide we will load the SMS Spam Collection dataset from HuggingFace: [link](https://huggingface.co/datasets/sms_spam). Each record of the dataset consists of a message and a label (spam or not). HuggingFace provides a nice [preview](<(https://huggingface.co/datasets/sms_spam)>) on the dataset.

```python
from datasets import load_dataset

# Load "sms_spam" dataset.
sms_dataset = load_dataset("sms_spam")

# Split train/test by 8:2.
sms_train_test = sms_dataset["train"].train_test_split(test_size=0.2)
train_dataset = sms_train_test["train"]
test_dataset = sms_train_test["test"]
```

## Data preprocessing

Let's do some data preprocessing before finetuning, we will do:

1. Tokenize the string data into a list of ints (token ids).
2. Pad the tokenized data to the same length, which is 128 tokens in this guide.
3. Shuffle the dataset.

```python
from transformers import AutoTokenizer

# Load the tokenizer for "distilbert-base-uncased" model.
tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")


def tokenize_function(examples):
    # Pad/truncate each text to 512 tokens. Enforcing the same shape
    # could make the training faster.
    return tokenizer(
        examples["sms"],
        padding="max_length",
        truncation=True,
        max_length=128,
    )


train_tokenized = train_dataset.map(tokenize_function)
train_tokenized = train_tokenized.remove_columns(["sms"]).shuffle(seed=42)

test_tokenized = test_dataset.map(tokenize_function)
test_tokenized = test_tokenized.remove_columns(["sms"]).shuffle(seed=42)
```

## Set up finetuning pipeline

Now let's go ahead setting up our finetuning pipeline. We will use HuggingFace `Trainer` API to finetune our model.

Let's load `DistilledBert` model from HuggingFace. We will use class `AutoModelForSequenceClassification`, which basically gives a DistilledBert model plus a fully connected layer to map the feature representation to probability distribution over our classes.

```python
from transformers import AutoModelForSequenceClassification

# Set the mapping between int label and its meaning.
id2label = {0: "ham", 1: "spam"}
label2id = {"ham": 0, "spam": 1}

model = AutoModelForSequenceClassification.from_pretrained(
    "distilbert-base-uncased",
    num_labels=2,
    label2id=label2id,
    id2label=id2label,
)
```

Create the evaluation metric to log. Loss is also logged, but adding other metrics such as accuracy can make modeling performance easier to understand. For classification task, we use `accuracy` as the tracking metric.

```python
import numpy as np
import evaluate

metric = evaluate.load("accuracy")


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return metric.compute(predictions=predictions, references=labels)
```

Let's set up the trainer! We need to configure two things:

- `TrainingArguments`: it sets hyperparameters like batch size, logging frequency and so. Please refer to [transformers documentation](https://huggingface.co/docs/transformers/main_classes/trainer#transformers.TrainingArguments)
  for the full arg list. Don't panick on the long list of args, usually we just need a few out of that.
- `Trainer`: `Trainer` hooks things together, including the model, training args, training/evaluation dataset, and evaluation function.

```python
from transformers import TrainingArguments, Trainer

# Checkpoints will be output to this `training_output_dir`.
training_output_dir = "sms_trainer"
training_args = TrainingArguments(
    output_dir=training_output_dir,
    evaluation_strategy="epoch",
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    logging_steps=8,
)

# Put things together with a `Trainer` instance.
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_tokenized,
    eval_dataset=test_tokenized,
    compute_metrics=compute_metrics,
)
```

We are ready for kicking off the training! Before that, let's set up our tracking/visualization tool - MLflow + Databricks (Community Edition).

## Set up tracking/visualization tool

If you have not, please register an account of [Databricks community edition](https://www.databricks.com/try-databricks#account). It should take no longer than 1min to register.

Databricks CE (community edition) is a free platform for users to try out Databricks features. For this guide, we need the ML experiment dashboard for us to track our training progress.

After you have sucessfully registered an account, all you need to do is to run the command below to connect from Google Colab to your Databricks account. You will need to enter following information at prompt:

- **Databricks Host**: https://community.cloud.databricks.com/
- **Username**: your signed up email
- **Password**: your password

```python
!databricks configure
```

If you have access to Databricks production version, you will need to run `!databricks configure --token` instead, and generate a **personal access token** in your account and paste it. Other setups are the same.

Now this colab is connected to the hosted tracking server. Let's configure MLflow metadata. Two things to set up:

- `mlflow.set_tracking_uri`: always use "databricks".
- `mlflow.set_experiment`: pick up a name you like, start with `/`

```python
import mlflow

# This is always "databricks" when using a databricks hosted tracking server.
mlflow.set_tracking_uri("databricks")
# Pick up a name you like.
mlflow.set_experiment("/finetune-a-spam-classifier")
```

## Kick off the finetuning

We have every piece! Now let's kick off the finetuning.

```python
with mlflow.start_run() as run:
    trainer.train()
```

While your training is ongoing, you can find this training in your dashboard. Log in to your [Databricks CE](https://community.cloud.databricks.com/) account, and click on top left to select machine learning in the drop down list. Then click on the experiment icon. See the screenshot below:
![landing page](https://drive.google.com/uc?export=view&id=1QxVaolr-L-w96pKUOiYQut3aSRE-04tC)

After clicking the `Experiment` button, it will bring you to the experiment page, where you can find your runs. Clicking on the most recent experiment and run, you can find your metrics there, similar to:
![experiment page](https://drive.google.com/uc?export=view&id=1M-oycljsFAHBVip81Rprwx57Ape1uCq-)

You can click on metrics to see the chart.

## Evaluate the finetuned model

Now we have finished the finetuning, let's see how it works. We will wrap the finetuned model into a HuggingFace `text-classification` pipeline. Using pipeline is optional, but it has several benefits including it automatically does tokenization and detokenization, so we can feed a string input and get a string output.

```python
from transformers import pipeline

pipe = pipeline(
    "text-classification",
    model=trainer.model,
    batch_size=8,
    tokenizer=tokenizer,
    device=0,
)

# Make a random message.
sample_text = (
    "WINNER!! As a valued network customer you have been selected "
    "to receivea £900 prize reward! To claim call 1234567. Claim "
    "code GEEZ. Valid 12 hours only."
)
print("Model prediction: ", pipe(sample_text))
```

That's it! You have made it, thanks for reading!
