"""
Mental Health BERT Model - Loads your trained model.
Replace your existing mental_health_bert.py with this version.
"""
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import numpy as np
import logging
import json
import re
from datetime import datetime
from pathlib import Path


class MentalHealthBERT:
    """
    Mental Health BERT model that loads your trained model.
    """
    
    def __init__(self, model_path="./trained_mental_health_bert"):
        """
        Initialize with your trained model.
        
        Args:
            model_path (str): Path to your trained model directory
        """
        self.logger = logging.getLogger(__name__)
        self.is_loaded = False
        self.model_path = Path(model_path)
        
        # Crisis keywords for immediate detection
        self.crisis_keywords = [
            'suicide', 'kill myself', 'end my life', 'want to die', 
            'harm myself', 'self harm', 'cutting', 'overdose',
            'jump off', 'hanging', 'pills', 'not worth living',
            'better off dead', 'end it all', 'give up', 'hopeless'
        ]
        
        # Crisis response
        self.crisis_response = {
            "response": "I'm very concerned about what you've shared. Please reach out for immediate help:\n\n🆘 National Suicide Prevention Lifeline: 988\n📱 Crisis Text Line: Text HOME to 741741\n🚨 Emergency Services: 911\n\nYou don't have to go through this alone. Your life has value, and there are people who want to help.",
            "confidence": 0.95
        }
        
        try:
            self._load_trained_model()
            self.is_loaded = True
            self.logger.info("✅ Trained Mental Health BERT model loaded successfully")
        except Exception as e:
            self.logger.error(f"❌ Error loading trained model: {e}")
            self._load_fallback_responses()
            self.is_loaded = False
    
    def _load_trained_model(self):
        """Load your trained BERT model."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model directory not found: {self.model_path}")
        
        # Load label mappings
        mappings_path = self.model_path / "label_mappings.json"
        if mappings_path.exists():
            with open(mappings_path, 'r') as f:
                mappings = json.load(f)
            self.intent_to_id = mappings['intent_to_id']
            self.id_to_intent = mappings['id_to_intent']
            self.num_labels = mappings['num_labels']
        else:
            raise FileNotFoundError("Label mappings not found. Make sure training completed successfully.")
        
        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        
        # Load model
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
        
        # Set device
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        self.model.eval()  # Set to evaluation mode
        
        # Load training config if available
        config_path = self.model_path / "training_config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                self.training_config = json.load(f)
                self.max_length = self.training_config.get('max_length', 512)
        else:
            self.max_length = 512
        
        self.logger.info(f"📊 Model info:")
        self.logger.info(f"   Intents: {list(self.intent_to_id.keys())}")
        self.logger.info(f"   Device: {self.device}")
        self.logger.info(f"   Max length: {self.max_length}")
    
    def _load_fallback_responses(self):
        """Load fallback responses if model loading fails."""
        self.fallback_responses = {
            'anxiety': [
                "I understand you're feeling anxious. Try taking slow, deep breaths. Breathe in for 4 counts, hold for 4, then breathe out for 4.",
                "Anxiety can feel overwhelming. Consider grounding yourself by naming 5 things you can see, 4 you can touch, 3 you can hear, 2 you can smell, and 1 you can taste.",
            ],
            'depression': [
                "I hear that you're going through a difficult time. Depression can make everything feel harder, but please know that you're not alone.",
                "When depression feels heavy, sometimes small steps can help. Even tiny achievements are victories worth acknowledging.",
            ],
            'stress': [
                "Stress can be challenging to manage. One technique that might help is progressive muscle relaxation.",
                "It sounds like you're dealing with a lot. Breaking big problems into smaller, manageable steps can help.",
            ],
            'general_support': [
                "Thank you for sharing with me. It takes courage to talk about what you're experiencing.",
                "I'm here to listen and support you. What's been on your mind lately?",
            ]
        }
    
    def check_for_crisis(self, text):
        """
        Check if the text contains crisis-related content.
        
        Args:
            text (str): Input text to analyze
            
        Returns:
            bool: True if crisis content is detected
        """
        text_lower = text.lower()
        
        # Method 1: Direct keyword matching
        direct_crisis = any(keyword in text_lower for keyword in self.crisis_keywords)
        
        # Method 2: Pattern matching for indirect crisis language
        crisis_patterns = [
            r"(don\'t|cant|cannot).*(live|go on)",
            r"(end|ending).*(everything|it all)",
            r"(no.*(point|reason|hope))",
            r"(give up|giving up)",
            r"(worthless|useless|burden)"
        ]
        
        pattern_crisis = any(re.search(pattern, text_lower) for pattern in crisis_patterns)
        
        # Method 3: If model is loaded, use it for crisis detection
        model_crisis = False
        if self.is_loaded:
            try:
                prediction = self.classify_intent(text)
                model_crisis = prediction['intent'] == 'crisis' and prediction['confidence'] > 0.7
            except:
                pass
        
        return direct_crisis or pattern_crisis or model_crisis
    
    def classify_intent(self, text):
        """
        Classify the intent of user input using your trained BERT model.
        
        Args:
            text (str): User input text
            
        Returns:
            dict: Intent classification results
        """
        if not self.is_loaded:
            return {'intent': 'general_support', 'confidence': 0.1, 'all_scores': {}}
        
        try:
            # Preprocess text
            cleaned_text = self.preprocess_text(text)
            
            # Tokenize
            inputs = self.tokenizer(
                cleaned_text,
                return_tensors="pt",
                truncation=True,
                padding='max_length',
                max_length=self.max_length
            )
            
            # Move to device
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Get predictions
            with torch.no_grad():
                outputs = self.model(**inputs)
                predictions = F.softmax(outputs.logits, dim=-1)
            
            # Get top prediction
            predicted_intent_idx = torch.argmax(predictions, dim=-1).item()
            confidence = predictions[0][predicted_intent_idx].item()
            
            intent = self.id_to_intent[str(predicted_intent_idx)]
            
            # Get all scores
            all_scores = {
                self.id_to_intent[str(i)]: score.item() 
                for i, score in enumerate(predictions[0])
            }
            
            return {
                'intent': intent,
                'confidence': confidence,
                'all_scores': all_scores
            }
            
        except Exception as e:
            self.logger.error(f"Error in intent classification: {e}")
            return {
                'intent': 'general_support',
                'confidence': 0.1,
                'all_scores': {}
            }
    
    def generate_response(self, text, intent, confidence):
        """
        Generate a therapeutic response based on intent and context.
        
        Args:
            text (str): User input
            intent (str): Classified intent
            confidence (float): Classification confidence
            
        Returns:
            str: Generated response
        """
        try:
            # Load response templates based on trained intents
            response_templates = self._get_response_templates()
            
            if intent in response_templates:
                import random
                base_response = random.choice(response_templates[intent])
                
                # Add personalization based on user input
                personalized_response = self._personalize_response(base_response, text, confidence)
                return personalized_response
            else:
                # Fallback to general support
                return random.choice(response_templates.get('general_support', [
                    "I'm here to listen and support you. Can you tell me more about how you're feeling?"
                ]))
                
        except Exception as e:
            self.logger.error(f"Error generating response: {e}")
            return "I'm here to support you. Can you share more about what you're experiencing?"
    
    def _get_response_templates(self):
        """Get response templates for each intent."""
        return {
            'anxiety': [
                "I can hear that you're feeling anxious. Anxiety is your body's natural response to stress. One technique that many find helpful is the 4-7-8 breathing method: breathe in for 4, hold for 7, exhale for 8. Would you like to try this?",
                "Anxiety can feel overwhelming, but you're taking a brave step by talking about it. Have you noticed any specific triggers? Understanding patterns can help us manage them better.",
                "When anxiety feels intense, grounding techniques can help. Try the 5-4-3-2-1 method: name 5 things you see, 4 you can touch, 3 you hear, 2 you smell, and 1 you taste."
            ],
            'depression': [
                "Thank you for sharing something so personal. Depression can make everything feel heavier, but please know that what you're experiencing is valid and treatable. You don't have to carry this alone.",
                "Depression often tells us lies - that we're not worthy, that things won't get better. These thoughts are symptoms of depression, not truths about who you are.",
                "Even small steps matter when dealing with depression. Sometimes just getting out of bed is a victory worth celebrating. What's one small thing you could try today?"
            ],
            'crisis': [
                "I'm very concerned about what you've shared. Your life has value, and there are people who want to help you through this difficult time. Please reach out for immediate support:\n\n🆘 National Suicide Prevention Lifeline: 988\n📱 Crisis Text Line: Text HOME to 741741\n🚨 Emergency Services: 911"
            ],
            'stress': [
                "Stress is your body's way of responding to demands, and it sounds like you're dealing with quite a lot. It's important to acknowledge that stress shouldn't be something you manage alone.",
                "When we're stressed, our minds often race between past regrets and future worries. One helpful practice is focusing on what you can control right now. What's one thing within your control today?",
                "Chronic stress can impact both mental and physical health. Have you been able to incorporate any stress-relief activities? Even 5-10 minutes of deep breathing can make a difference."
            ],
            'sleep': [
                "Sleep difficulties can significantly impact mental health. Try creating a bedtime routine - dimming lights, avoiding screens 1 hour before bed, and keeping your room cool and dark.",
                "If you're having trouble sleeping, your mind might be too active. Consider trying progressive muscle relaxation or gentle breathing exercises before bed.",
                "Sleep and mental health are closely connected. Consistent sleep schedules, even on weekends, can help regulate your body's internal clock."
            ],
            'general_support': [
                "Thank you for reaching out. It takes courage to share what you're experiencing. I'm here to listen and support you.",
                "I hear you, and I want you to know that your feelings are valid. What's been weighing on your mind lately?",
                "You've taken an important step by talking about this. How can I best support you today?"
            ]
        }
    
    def _personalize_response(self, base_response, user_text, confidence):
        """Add personalization to the response based on user input."""
        text_lower = user_text.lower()
        
        # Add context-specific additions
        additions = []
        
        if 'work' in text_lower or 'job' in text_lower:
            additions.append("I notice you mentioned work-related concerns. Workplace stress is very common and valid.")
        
        if 'family' in text_lower or 'relationship' in text_lower:
            additions.append("Relationship challenges can significantly impact our wellbeing.")
        
        if 'school' in text_lower or 'study' in text_lower or 'exam' in text_lower:
            additions.append("Academic pressure can be really challenging to navigate.")
        
        if confidence < 0.6:
            additions.append("I want to make sure I understand you correctly - please feel free to share more details.")
        
        # Combine base response with additions
        full_response = base_response
        if additions:
            full_response += "\n\n" + " ".join(additions)
        
        return full_response
    
    def get_response(self, text):
        """
        Main method to get a response for user input.
        
        Args:
            text (str): User input
            
        Returns:
            dict: Complete response data
        """
        try:
            # Check for crisis first
            if self.check_for_crisis(text):
                return {
                    "response": self.crisis_response["response"],
                    "confidence": self.crisis_response["confidence"],
                    "topic": "crisis",
                    "model": "bert_crisis_detection",
                    "intent_scores": {"crisis": 0.95}
                }
            
            # Classify intent using trained model
            if self.is_loaded:
                intent_result = self.classify_intent(text)
                intent = intent_result['intent']
                confidence = intent_result['confidence']
                intent_scores = intent_result['all_scores']
                model_name = "trained_bert_model"
            else:
                # Fallback to simple classification
                intent = self._simple_intent_detection(text)
                confidence = 0.3
                intent_scores = {intent: 0.3}
                model_name = "fallback_model"
            
            # Generate response
            response_text = self.generate_response(text, intent, confidence)
            
            return {
                "response": response_text,
                "confidence": confidence,
                "topic": intent,
                "model": model_name,
                "intent_scores": intent_scores
            }
            
        except Exception as e:
            self.logger.error(f"Error in get_response: {e}")
            return {
                "response": "I'm here to support you. Please feel free to share what's on your mind.",
                "confidence": 0.1,
                "topic": "error",
                "model": "error_fallback",
                "intent_scores": {}
            }
    
    def _simple_intent_detection(self, text):
        """Simple keyword-based intent detection as fallback."""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['anxious', 'anxiety', 'worried', 'panic']):
            return 'anxiety'
        elif any(word in text_lower for word in ['depressed', 'depression', 'sad', 'hopeless']):
            return 'depression'
        elif any(word in text_lower for word in ['stressed', 'stress', 'overwhelmed']):
            return 'stress'
        elif any(word in text_lower for word in ['sleep', 'insomnia', 'tired']):
            return 'sleep'
        else:
            return 'general_support'
    
    def get_crisis_response(self):
        """Get immediate crisis response."""
        return self.crisis_response
    
    def preprocess_text(self, text):
        """
        Preprocess text for BERT processing.
        
        Args:
            text (str): Raw input text
            
        Returns:
            str: Cleaned text
        """
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep emoticons and basic punctuation
        text = re.sub(r'[^\w\s\.\!\?\:\;\-\(\)]', ' ', text)
        
        # Standardize common abbreviations
        text = text.replace("im ", "i am ")
        text = text.replace("dont ", "don't ")
        text = text.replace("cant ", "can't ")
        text = text.replace("wont ", "won't ")
        
        return text.strip()
    
    def get_model_info(self):
        """Get information about the loaded model."""
        if self.is_loaded:
            return {
                'model_path': str(self.model_path),
                'intents': list(self.intent_to_id.keys()),
                'num_labels': self.num_labels,
                'device': str(self.device),
                'max_length': self.max_length,
                'is_trained': True
            }
        else:
            return {
                'model_path': 'Not loaded',
                'intents': ['Using fallback responses'],
                'num_labels': 0,
                'device': 'CPU',
                'max_length': 512,
                'is_trained': False
            }