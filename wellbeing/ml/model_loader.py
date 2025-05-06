"""
Module for initializing ML models used in the application
"""
import os
import logging
import tensorflow as tf
import joblib
import json
from flask import current_app
from wellbeing import bert_model

# Global variables for the original model components
original_model = None
original_tokenizer = None
original_label_encoder = None
original_responses = None
original_model_loaded = False

def initialize_original_model():
    """Initialize the original model"""
    global original_model, original_tokenizer, original_label_encoder, original_responses, original_model_loaded
    try:
        original_model = tf.keras.models.load_model("model/chatbot_lstm_gru_glove.keras")
        original_tokenizer = joblib.load("model/tokenizer.pkl")
        original_label_encoder = joblib.load("model/label_encoder.pkl")
        
        with open("model/intents_expanded.json", 'r', encoding='utf-8') as file:
            intents = json.load(file)
        original_responses = {intent["tag"]: intent["responses"] for intent in intents["intents"]}
        
        original_model_loaded = True
        current_app.logger.info("Original model loaded successfully")
        return True
    except Exception as e:
        current_app.logger.error(f"Error loading original model: {e}")
        original_model_loaded = False
        return False

def initialize_bert_model():
    """Initialize the BERT model"""
    global bert_model
    try:
        from mental_health_bert import MentalHealthBERT
        bert_model = MentalHealthBERT()
        current_app.logger.info("DistilBERT model loaded successfully")
        return bert_model.is_loaded
    except Exception as e:
        current_app.logger.error(f"Error loading DistilBERT model: {str(e)}")
        return False