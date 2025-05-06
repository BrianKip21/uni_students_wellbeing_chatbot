"""
Interface for accessing the BERT model
"""
from wellbeing import bert_model

def get_bert_model():
    """
    Get the BERT model instance.
    
    Returns:
        MentalHealthBERT: The BERT model instance
    """
    return bert_model

def check_for_crisis(text):
    """
    Check if text indicates a crisis situation.
    
    Args:
        text (str): Text to analyze
        
    Returns:
        bool: True if text indicates a crisis, False otherwise
    """
    if bert_model and bert_model.is_loaded:
        return bert_model.check_for_crisis(text)
    return False

def get_response(text):
    """
    Get a response for the given text.
    
    Args:
        text (str): Text to respond to
        
    Returns:
        dict: Response data including text, confidence, and topic
    """
    if bert_model and bert_model.is_loaded:
        return bert_model.get_response(text)
    return {
        "response": "I'm having trouble understanding. Could you try rephrasing your question?",
        "confidence": 0.0,
        "model": "fallback",
        "topic": "unknown"
    }