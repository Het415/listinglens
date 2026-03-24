import pandas as pd
from src.rag_chatbot import run_rag_pipeline, ask_question

df = pd.read_csv('data/processed/nlp_B08XPWDSWW.csv')
rag = run_rag_pipeline(df, 'B08XPWDSWW')

result = ask_question(rag['chain'], 'What are the most common complaints?')
print('A:', result['answer'])
print('Sources:', result['n_sources'])
