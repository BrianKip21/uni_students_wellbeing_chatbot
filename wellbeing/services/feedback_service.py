"""
Feedback analysis and processing service
"""
from datetime import datetime, timezone, timedelta
import os
import re
import json
import pandas as pd
from flask import current_app
from wellbeing import mongo, scheduler

def initialize_feedback_system():
    """Initialize the feedback collection and analysis system"""
    try:
        # Create MongoDB indexes for better performance
        mongo.db.chats.create_index([("user_id", 1)])
        mongo.db.chats.create_index([("timestamp", -1)])
        mongo.db.chats.create_index([("feedback.rating", 1)])
        mongo.db.chats.create_index([("feedback.was_helpful", 1)])
        mongo.db.chats.create_index([("conversation_context.topic", 1)])
        mongo.db.feedback.create_index([("chat_id", 1)])
        
        # Set up the scheduler for feedback analysis
        scheduler.add_job(
            scheduled_feedback_analysis, 
            'cron', 
            hour=2,
            minute=0
        )
        
        # Start the scheduler
        scheduler.start()
        
        current_app.logger.info("Feedback collection and analysis system initialized")
        
    except Exception as e:
        current_app.logger.error(f"Error initializing feedback system: {str(e)}")

def scheduled_feedback_analysis():
    """Scheduled task to analyze feedback and generate improvement recommendations"""
    try:
        current_app.logger.info("Running scheduled feedback analysis")
        
        # Perform the analysis
        recommendations = analyze_feedback_data()
        
        # Log the results
        current_app.logger.info(f"Completed feedback analysis: {len(recommendations)} recommendations")
        
    except Exception as e:
        current_app.logger.error(f"Error in scheduled feedback analysis: {str(e)}")

def analyze_feedback_data():
    """
    Analyzes feedback data to identify areas for improvement and generate recommendations.
    
    Returns:
        list: A list of recommendation dictionaries
    """
    try:
        # Get low-rated or unhelpful responses from the last week
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        problem_chats = list(mongo.db.chats.find({
            "$or": [
                {"feedback.was_helpful": False}, 
                {"feedback.rating": {"$lt": 3}}
            ],
            "timestamp": {"$gte": one_week_ago}
        }))
        
        # Group by topics
        topic_issues = {}
        for chat in problem_chats:
            topic = chat.get('conversation_context', {}).get('topic', 'unknown')
            if topic not in topic_issues:
                topic_issues[topic] = []
            topic_issues[topic].append({
                "query": chat['message'],
                "response": chat['response'],
                "confidence": chat.get('confidence', 0),
                "feedback": chat.get('feedback', {}).get('feedback_text', ''),
                "id": str(chat['_id'])
            })
        
        # Generate recommendations
        recommendations = []
        for topic, issues in topic_issues.items():
            if len(issues) >= 3:  # Only look at topics with multiple issues
                # Calculate average confidence for this topic
                avg_confidence = sum(issue.get('confidence', 0) for issue in issues) / len(issues)
                
                recommendations.append({
                    "topic": topic,
                    "count": len(issues),
                    "examples": issues[:3],  # Show a few examples
                    "avg_confidence": avg_confidence,
                    "suggestion": f"Add more training data for '{topic}' topic"
                })
        
        # Find patterns in frequently asked but poorly answered queries
        common_words = analyze_common_terms(problem_chats)
        
        # Save recommendations
        recommendation_doc = {
            "timestamp": datetime.now(timezone.utc),
            "recommendations": recommendations,
            "common_terms": common_words[:10],  # Top 10 problem terms
            "total_analyzed": len(problem_chats)
        }
        
        mongo.db.improvement_recommendations.insert_one(recommendation_doc)
        
        # Log the analysis
        current_app.logger.info(f"Feedback analysis complete: {len(recommendations)} topic recommendations generated")
        
        return recommendations
    
    except Exception as e:
        current_app.logger.error(f"Error analyzing feedback data: {str(e)}")
        return []

def analyze_common_terms(problem_chats):
    """
    Analyzes common terms in problematic chats to identify potential knowledge gaps.
    
    Args:
        problem_chats (list): List of chat documents with negative feedback
        
    Returns:
        list: A list of (term, frequency) tuples sorted by frequency
    """
    try:
        # Define common stop words to filter out
        stop_words = set([
            "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
            "at", "by", "for", "with", "about", "against", "between", "into",
            "through", "during", "before", "after", "above", "below", "to", "from",
            "up", "down", "in", "out", "on", "off", "over", "under", "again",
            "further", "then", "once", "here", "there", "all", "any", "both",
            "each", "few", "more", "most", "other", "some", "such", "no", "nor",
            "not", "only", "own", "same", "so", "than", "too", "very", "s", "t",
            "just", "don", "now", "d", "ll", "m", "o", "re", "ve", "y", "ain",
            "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn",
            "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn", "weren",
            "won", "wouldn", "how", "what", "why", "where", "when", "who", "which"
        ])
        
        all_terms = {}
        
        for chat in problem_chats:
            # Simple tokenization by splitting on spaces and removing punctuation
            terms = [term.strip(',.?!()[]{}":;').lower() 
                    for term in chat['message'].split() 
                    if len(term.strip(',.?!()[]{}":;')) > 3]  # Only terms with >3 chars
            
            # Filter out stop words
            filtered_terms = [term for term in terms if term not in stop_words]
            
            for term in filtered_terms:
                if term not in all_terms:
                    all_terms[term] = 0
                all_terms[term] += 1
        
        # Sort by frequency
        sorted_terms = sorted(all_terms.items(), key=lambda x: x[1], reverse=True)
        
        return sorted_terms
        
    except Exception as e:
        current_app.logger.error(f"Error analyzing common terms: {str(e)}")
        return []

def create_retraining_dataset():
    """Creates a retraining dataset for model fine-tuning"""
    try:
        # Ensure training data directory exists
        training_dir = os.path.join(current_app.root_path, 'ml', 'training_data')
        os.makedirs(training_dir, exist_ok=True)
        
        # Get chats with improved responses
        retraining_chats = list(mongo.db.chats.find({
            "retraining_status": "ready"
        }))
        
        if not retraining_chats:
            current_app.logger.info("No data ready for retraining")
            return
        
        # Format for model fine-tuning
        training_pairs = []
        for chat in retraining_chats:
            training_pairs.append({
                "query": chat['message'],
                "improved_response": chat['improved_response'],
                "original_response": chat['response'],
                "feedback": chat.get('feedback', {}).get('feedback_text', ''),
                "topic": chat.get('conversation_context', {}).get('topic', 'general')
            })
        
        # Save the training dataset
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"retraining_dataset_{timestamp}.json"
        
        with open(os.path.join(training_dir, filename), 'w') as f:
            json.dump(training_pairs, f)
        
        # Update status of processed chats
        chat_ids = [chat['_id'] for chat in retraining_chats]
        mongo.db.chats.update_many(
            {"_id": {"$in": chat_ids}},
            {"$set": {"retraining_status": "processed"}}
        )
        
        current_app.logger.info(f"Created retraining dataset with {len(training_pairs)} examples: {filename}")
        
    except Exception as e:
        current_app.logger.error(f"Error creating retraining dataset: {str(e)}")

def export_training_data(min_rating=4, helpful_only=True):
    """
    Exports high-quality training examples based on positive feedback
    
    Args:
        min_rating (int): Minimum rating threshold (1-5)
        helpful_only (bool): Whether to only include feedback marked as helpful
        
    Returns:
        pandas.DataFrame: DataFrame with training data or None if error
    """
    try:
        # Build query for chats with positive feedback
        query = {"feedback": {"$exists": True}}
        
        if helpful_only:
            query["feedback.was_helpful"] = True
        
        if min_rating > 0:
            query["feedback.rating"] = {"$gte": min_rating}
        
        # Get chats matching criteria
        positive_chats = list(mongo.db.chats.find(query))
        
        # Format for training
        training_data = []
        for chat in positive_chats:
            training_data.append({
                "query": chat['message'],
                "response": chat['response'],
                "confidence": chat.get('confidence', 0),
                "rating": chat.get('feedback', {}).get('rating', 0),
                "topic": chat.get('conversation_context', {}).get('topic', 'general')
            })
        
        # Create DataFrame
        if training_data:
            return pd.DataFrame(training_data)
        else:
            return None
            
    except Exception as e:
        current_app.logger.error(f"Error exporting training data: {str(e)}")
        return None