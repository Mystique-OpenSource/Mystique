# Patch Porting Approach

This folder contains the implementation of `Mystique`. The system is organized into five main modules, each playing a critical role in automating the porting of security patches across different branches at the function level.

## Dependencies

To run this project, you will need the following dependencies:

- `Python` - 3.11+
- `Joern` - 2.260 For code analysis and semantic/syntactic extraction
- `Tree-sitter` - 0.22.6
- `Clang-Tidy` - 14.0.0

The more detailed dependencies are in `requirements.txt`

## How to Run:

```py
python patchbp.py <json_data> <cveid>
```

## Modules

### 1. Patch Function Semantic & Syntactic Signature Extraction (`patchbp.py`, `ast_parser.py`, `project.py`, `joern.py`)

This module extracts both semantic and syntactic signatures from the patched functions. It utilizes Joern for static code analysis to identify code structures, control flow, and relevant variables.

**Input**: The patched code or functions  
**Output**: Semantic and syntactic signatures (AST, CFG, etc.)

### 2. Vulnerable Function Semantic & Syntactic Signature Extraction (`patchbp.py`, `ast_parser.py`, `project.py`, `joern.py`)

Similar to the patch function extraction, this module extracts the same signatures from the vulnerable code to identify how the vulnerability is structured.

**Input**: The vulnerable code or functions  
**Output**: Semantic and syntactic signatures of the vulnerable code

### 3. Patch Porting Prompt Generation (`patchbp.py`, `patch.py`)

This module generates prompts that guide the LLMs on how to port patches to other branches or repositories. It creates the necessary instructions using extracted signatures from both patched and vulnerable code.

**Input**: Semantic and syntactic signatures from both patched and vulnerable functions  
**Output**: A set of structured prompts for patch porting

### 4. LLM Fine-Tuning (via oobabooga/text-generation-webui)

This module integrates [oobabooga's text-generation-webui](https://github.com/oobabooga/text-generation-webui) to fine-tune the LLM specifically for patch porting tasks. We rely on this framework to generate the fine-tuned model using Low-Rank Adaptation (LoRA), which allows for efficient fine-tuning of large models on smaller datasets. We have uploaded all the datasets and parameters in Google Drive.
Reproduce the fine-tuned results of `Mystique` following the next steps:

**Input**: Pre-trained LLM, prompts template, datasets

1. git clone https://github.com/oobabooga/text-generation-webui.git

2. place-your-models-here:
   place [CodeLLama](https://huggingface.co/meta-llama/CodeLlama-13b-Instruct-hf) into the folder [models](https://github.com/oobabooga/text-generation-webui/tree/main/models)

3. place-your-finetune-template-here:
   place [designed template](https://drive.google.com/file/d/1_5HufOI4LA7qW1L7k0YPzmGnH3W1R-5s/view?usp=drive_link) into the folder [formats](https://github.com/oobabooga/text-generation-webui/tree/main/training/formats)

4. place-your-finetune-dataset-here:
   place [ft_merge](https://drive.google.com/drive/folders/1EGa2QtUcwq0KTzZiqVkNjhht2RDzuRnG?usp=drive_link) into the folder [datasets](https://github.com/oobabooga/text-generation-webui/tree/main/training/datasets)

**Output**: Fine-tuned Loras for patch porting

The output of Lora fine-tuned parameters is: [fine-tuned CodeLLama](https://drive.google.com/file/d/1tzXtglOo_aywKo4_MvwKTYTx-plE3wGT/view?usp=drive_link)

### 5. Fixed Function Generation (`llm.py`, `recover.py`, `check.py`)

Once the patches are applied, this module is responsible for generating the fixed version of the code. It ensures that the ported patches are applied correctly and verifies the fix through static analysis and validation.

**Input**: [Ported patch information](https://drive.google.com/drive/folders/1dc27pCylI38eJ8fig2JTkxgcCxsO9RMD?usp=drive_link)

**Output**: The fixed function of the target repository
