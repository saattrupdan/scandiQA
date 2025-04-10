'''Training script for finetuning a question-answering model.

This is based on the example at:
    https://colab.research.google.com/github/huggingface/notebooks/blob/master/examples/question_answering.ipynb
'''
from datasets import DatasetDict, load_metric, Dataset, concatenate_datasets
from datasets.features import Value
from transformers import (AutoModelForQuestionAnswering,
                          TrainingArguments,
                          default_data_collator,
                          Trainer)
from pathlib import Path
from typing import Dict
from collections import defaultdict
import json

from data_preparation import QAPreparer
from config import Config
import wandb


def train(dataset_dict: DatasetDict, output_model_id: str, config: Config):
    '''Finetune a pretrained model on a question-answering dataset.

    Args:
        dataset_dict (DatasetDict):
            The train/val splits of the question-answering dataset to finetune
            the model on.
        output_model_id (str):
            The name of the output model.
        config (Config):
            The configuration for the finetuning.
    '''
    # Set up wandb
    wandb.init(project='texas', entity='saattrupdan')
    wandb.config = dict(config)

    # Initialise the QA preparer
    preparer = QAPreparer(config)

    # Prepare the dataset for training
    prepared = preparer.prepare_train_val_datasets(dataset_dict)

    # Load the model
    model = AutoModelForQuestionAnswering.from_pretrained(config.model_id)

    # Prepare the training arguments
    args = TrainingArguments(
        output_dir=output_model_id.split('/')[-1],
        evaluation_strategy = 'steps',
        eval_steps=1000,
        logging_steps=100,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        num_train_epochs=config.epochs,
        weight_decay=config.weight_decay,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        adam_beta1=config.betas[0],
        adam_beta2=config.betas[1],
        push_to_hub=True,
        hub_model_id=output_model_id
    )

    # Initialise the trainer
    trainer = Trainer(
        model,
        args,
        train_dataset=prepared['train'],
        eval_dataset=prepared['validation'],
        data_collator=default_data_collator,
        tokenizer=preparer.tokenizer
    )

    # Finetune the model
    trainer.train()

    # Initialise the test dataset
    test_dataset = dataset_dict['validation']

    # Evaluate the model
    scores = evaluate(test_dataset, trainer, preparer)

    # Print the results
    print(f'EM: {scores["em"]:.3f}')
    print(f'F1: {scores["f1"]:.3f}')

    # Store the scores
    score_path = Path(f'{output_model_id.split("/")[-1]}-scores.jsonl')
    with score_path.open('w') as f:
        jsonned = json.dumps(scores)
        f.write(jsonned)

    # Stop Wandb logging
    wandb.finish()

    # Push to hub
    if config.push_to_hub:
        trainer.push_to_hub()



def evaluate(test_dataset: Dataset,
             trainer: Trainer,
             preparer: QAPreparer) -> Dict[str, float]:
    '''Evaluate the finetuned model on a test dataset.

    Args:
        test_dataset (Dataset):
            The test dataset to evaluate the model on.
        trainer (Trainer):
            The trainer object to use to evaluate the model.
        preparer (QAPreparer):
            The preparer object to use to prepare the test dataset.

    Returns:
        Dict[str, float]:
            A dictionary containing the EM and F1 scores.
    '''
    # Prepare the test dataset
    prepared_test = preparer.prepare_test_dataset(test_dataset)

    # Get test predictions
    predictions = trainer.predict(prepared_test)

    # Postprocess the predictions
    predictions = preparer.postprocess_predictions(
        test_dataset=test_dataset,
        prepared_test_dataset=prepared_test,
        predictions=predictions
    )

    # Load metric
    metric = load_metric('squad_v2')

    # Compute metric scores
    predictions = [
        dict(id=k, prediction_text=v, no_answer_probability=0.)
        for k, v in predictions.items()
    ]
    references = [
        dict(id=example['id'],
             answers=dict(text=example['answers']['text'],
                          answer_start=example['answers']['answer_start']))
        for example in test_dataset
    ]
    scores = metric.compute(predictions=predictions, references=references)

    # Return the scores
    return dict(em=scores['exact'], f1=scores['f1'])


if __name__ == "__main__":
    import sys

    # Set language code
    if len(sys.argv) > 1:
        language_code = sys.argv[1]
    else:
        raise ValueError('Please provide a language code')

    # Load datasets
    squad = DatasetDict.from_json(dict(
        train=f'datasets/squad_v2-train-{language_code}.jsonl',
        validation=f'datasets/squad_v2-validation-{language_code}.jsonl'
    ))
    # fquad = DatasetDict.from_json(dict(
    #     train=f'datasets/fquad-train-{language_code}.jsonl',
    #     validation=f'datasets/fquad-validation-{language_code}.jsonl'
    # ))
    # gquad = DatasetDict.from_json(dict(
    #     train=f'datasets/deepset-germanquad-train-{language_code}.jsonl',
    #     validation=f'datasets/deepset-germanquad-test-{language_code}.jsonl'
    # ))
    # aqa = DatasetDict.from_json(dict(
    #     train=f'datasets/adversarial_qa-adversarialQA-train-{language_code}.jsonl',
    #     validation=f'datasets/adversarial_qa-adversarialQA-validation-{language_code}.jsonl'
    # ))
    # sberquad = DatasetDict.from_json(dict(
    #     train=f'datasets/sberquad-train-{language_code}.jsonl',
    #     validation=f'datasets/sberquad-validation-{language_code}.jsonl'
    # ))

    # Ensure that the datasets have the `id` feature as string
    # datasets = defaultdict(list)
    # for dataset in [squad, fquad, gquad, aqa, sberquad]:
    #     dataset_feats = dataset['train'].features.copy()
    #     dataset_feats['id'] = Value('string')
    #     dataset = dataset.cast(dataset_feats)
    #     datasets['train'].append(dataset['train'])
    #     datasets['validation'].append(dataset['validation'])

    # train_dict = concatenate_datasets(datasets['train']).shuffle().to_dict()
    # train_dict['id'] = list(range(len(train_dict)))
    # train_dataset = Dataset.from_dict(train_dict)
    # val_dict = concatenate_datasets(datasets['validation']).shuffle().to_dict()
    # val_dict['id'] = list(range(len(train_dict),
    #                             len(train_dict) + len(val_dict)))
    # val_dataset = Dataset.from_dict(val_dict)
    # dataset_dict = DatasetDict()
    # dataset_dict['train'] = train_dataset
    # dataset_dict['validation'] = val_dataset

    # Load config
    config = Config()

    # Train the model
    train(squad,  # dataset_dict,
          output_model_id=f'saattrupdan/xlmr-base-texas-squad-{language_code}',
          config=config)
