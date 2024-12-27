
from datetime import timedelta, datetime as dt
import os
from dotenv import load_dotenv
import re
import warnings

from fontTools.subset import neuter_lookups
from sympy.multipledispatch.dispatcher import ambiguity_register_error_ignore_dup

from _class.SentimentCahe import SentimentCache

from newsapi import NewsApiClient
from bs4 import BeautifulSoup

import numpy as np
import pandas as pd

from transformers import BertTokenizer, BertForSequenceClassification
from transformers import pipeline
import torch

from typing import Optional
from CustomTypes import Days

class Sentiment:
    """
    FinBERT Sentiment Analysis for Financial News.
    """
    def __init__(self):
        load_dotenv('_class/api.env')

        if os.getenv('API_KEY') == None:
            raise ValueError("API_KEY not found in environment variables")

        self.tokenizer = BertTokenizer.from_pretrained('yiyanghkust/finbert-tone')
        self.model = BertForSequenceClassification.from_pretrained('yiyanghkust/finbert-tone')
        self.cache = self._init_cache()

    @staticmethod
    def _init_cache(name: str = 'sentiment.db', exp_after: int = 3600) -> SentimentCache:
        return SentimentCache(name, exp_after)

    @staticmethod
    def search(query: str, *, n: int, lookback: Days) -> list:
        key = os.getenv('API_KEY')
        newsapi = NewsApiClient(api_key=key)

        date = dt.today() - timedelta(days=lookback)

        articles = newsapi.get_everything(q=query,
                                          from_param=date,
                                          language='en',
                                          sort_by='publishedAt',
                                          page_size=n)

        filtered_articles = []
        neutral_string = 'confident.' # Evaluates to a sentiment polarity of \approx 0.0 (neutral)
        for article in articles['articles']:
            if (article['description'] is None or article['description'] == '') and \
                    (article['title'] is None or article['title'] == ''):
                continue  # Skip articles with both description and title as None or empty

            # Ensure no None values remain
            if article['description'] is None:
                article['description'] = neutral_string
            if article['title'] is None:
                article['title'] = neutral_string

            filtered_articles.append(article)

        desc = [article['description'] + ' ' + article['title'] for article in filtered_articles]

        return desc

    def get_score_all(self, text: str) -> dict:
        inputs = self.tokenizer(text, return_tensors='pt', padding=True, truncation=True)
        outputs = self.model(**inputs)

        logits = outputs.logits.squeeze()
        p_val = torch.nn.functional.softmax(logits, dim=-1).detach().numpy()

        return p_val

    def compose_sentiment(self, text: str) -> str:
        p_val = self.get_score_all(text)

        score = p_val[2] - p_val[0]
        return score

    def get_sentiment(self, query: str, n: int, lookback: Days) -> float:
        cache_query = f"{query} {lookback=} {n=}"

        cache_response = self.cache.get(cache_query)

        # Cache hit
        if cache_response is not None:
            return cache_response

        # Cache miss
        search_results = self.search(query, n=n, lookback=lookback)
        sentiments = []

        for desc in search_results:
            score = self.compose_sentiment(desc)
            sentiments.append(score)

        if sentiments == []:
            self.cache.cache(cache_query, 0.5)
            return .5  # Neutral if no sentiment found

        ewma_sentiment = pd.Series(sentiments).ewm(halflife=2).mean().iloc[-1]
        self.cache.cache(cache_query, ewma_sentiment)
        return ewma_sentiment


