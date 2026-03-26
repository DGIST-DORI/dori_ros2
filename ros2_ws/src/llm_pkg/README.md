# llm_pkg

## build_index.py

Index builder for DORI Knowledge Base

### Install Dependencies

pip install sentence-transformers faiss-cpu numpy

### First Build

python3 build_index.py --docs ./data/campus/processed --output ./rag_index

### Quick update after adding diet file

python3 build_index.py --docs ./data/campus/processed --output ./rag_index --incremental