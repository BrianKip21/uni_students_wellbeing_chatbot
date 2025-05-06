"""
Module for retraining chatbot models based on user feedback
"""
import os
import json
import pandas as pd
import tensorflow as tf
from datetime import datetime, timezone
from flask import current_app, url_for, flash, session
from werkzeug.utils import secure_filename
from wellbeing import mongo, logger
from wellbeing.ml.bert_model import get_bert_model
from wellbeing.ml.model_loader import initialize_original_model, original_model, original_tokenizer, original_label_encoder

def process_improved_responses(file_path):
    """
    Process uploaded improved responses CSV and update models
    
    Args:
        file_path (str): Path to the uploaded CSV file
        
    Returns:
        dict: Results of the retraining process
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return {"success": False, "message": "File not found"}
        
        # Read the CSV file
        df = pd.read_csv(file_path)
        
        # Check required columns
        required_columns = ['query', 'improved_response', 'topic', 'model']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return {
                "success": False, 
                "message": f"Missing required columns: {', '.join(missing_columns)}"
            }
        
        # Split into different model improvements
        bert_improvements = df[df['model'] == 'bert']
        original_improvements = df[df['model'] == 'original']
        
        results = {
            "bert_updated": False,
            "original_updated": False,
            "bert_count": len(bert_improvements),
            "original_count": len(original_improvements)
        }
        
        # Process BERT model improvements
        if not bert_improvements.empty:
            bert_result = update_bert_model(bert_improvements)
            results.update(bert_result)
        
        # Process original model improvements
        if not original_improvements.empty:
            original_result = update_original_model(original_improvements)
            results.update(original_result)
        
        # Save a copy of the processed data for reference
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        processed_dir = os.path.join(current_app.instance_path, 'processed_feedback')
        os.makedirs(processed_dir, exist_ok=True)
        processed_file = os.path.join(processed_dir, f'processed_feedback_{timestamp}.csv')
        df.to_csv(processed_file, index=False)
        
        # Log the retraining action
        mongo.db.admin_logs.insert_one({
            "action": "retrain_models",
            "timestamp": datetime.now(timezone.utc),
            "admin_id": session.get("user", "unknown"),  # Changed here
            "bert_count": results.get("bert_count", 0),
            "original_count": results.get("original_count", 0),
            "success": True,
            "processed_file": processed_file
        })
        
        return {
            "success": True,
            "message": "Processed improved responses successfully",
            "processed_file": processed_file,
            **results
        }
    
    except Exception as e:
        logger.error(f"Error processing improved responses: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Log the error
        mongo.db.admin_logs.insert_one({
            "action": "retrain_models",
            "timestamp": datetime.now(timezone.utc),
            "admin_id": session.get("user", "unknown"),  # Changed here
            "success": False,
            "error": str(e)
        })
        
        return {"success": False, "message": f"Error: {str(e)}"}

def update_bert_model(improvements_df):
    """
    Update the BERT model with improved responses
    
    Args:
        improvements_df (DataFrame): DataFrame with improved responses
        
    Returns:
        dict: Results of the update process
    """
    try:
        # Get the BERT model instance
        bert_model = get_bert_model()
        if not bert_model or not hasattr(bert_model, 'is_loaded') or not bert_model.is_loaded:
            logger.error("BERT model not available for updating")
            return {"bert_error": "BERT model not available", "bert_updated": False}
        
        # Check if model supports updating responses
        if not hasattr(bert_model, 'update_responses'):
            logger.error("BERT model does not support updating responses")
            
            # Create a training dataset file that could be used later
            create_bert_training_file(improvements_df)
            
            return {
                "bert_error": "BERT model does not support direct response updates. Created training file instead.",
                "bert_updated": False
            }
        
        # Prepare data for update
        queries = improvements_df['query'].tolist()
        responses = improvements_df['improved_response'].tolist()
        topics = improvements_df['topic'].tolist()
        
        # Update the model responses
        update_result = bert_model.update_responses(queries, responses, topics)
        
        # Save updated model if applicable
        if hasattr(bert_model, 'save'):
            bert_model.save()
            logger.info("BERT model saved successfully after updating responses")
        
        return {
            "bert_updated": True,
            "bert_update_details": update_result
        }
    
    except Exception as e:
        logger.error(f"Error updating BERT model: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Create a training file as fallback
        try:
            create_bert_training_file(improvements_df)
            return {
                "bert_error": f"Error updating BERT model: {str(e)}. Created training file instead.",
                "bert_updated": False
            }
        except:
            return {"bert_error": str(e), "bert_updated": False}

def create_bert_training_file(improvements_df):
    """
    Create a training file for BERT model if direct updating is not supported
    
    Args:
        improvements_df (DataFrame): DataFrame with improved responses
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    training_dir = os.path.join(current_app.instance_path, 'bert_training')
    os.makedirs(training_dir, exist_ok=True)
    training_file = os.path.join(training_dir, f'bert_training_{timestamp}.json')
    
    # Convert to the format required for BERT fine-tuning
    training_data = []
    for _, row in improvements_df.iterrows():
        training_data.append({
            "input": row['query'],
            "output": row['improved_response'],
            "topic": row['topic']
        })
    
    # Save as JSON for later use
    with open(training_file, 'w') as f:
        json.dump(training_data, f, indent=2)
    
    logger.info(f"Created BERT training file with {len(training_data)} examples: {training_file}")

def update_original_model(improvements_df):
    """
    Update the original model with improved responses by modifying the intents file
    
    Args:
        improvements_df (DataFrame): DataFrame with improved responses
        
    Returns:
        dict: Results of the update process
    """
    try:
        # Check if original model is available
        if original_model is None:
            logger.error("Original model not available for updating")
            return {"original_error": "Original model not available", "original_updated": False}
        
        # Load the current intents file
        intents_file_path = os.path.join("model", "intents_expanded.json")
        
        # Create a backup of the intents file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(current_app.instance_path, 'backups')
        os.makedirs(backup_path, exist_ok=True)
        backup_file = os.path.join(backup_path, f'intents_backup_{timestamp}.json')
        
        with open(intents_file_path, 'r', encoding='utf-8') as f:
            intents_data = json.load(f)
            
            # Save backup
            with open(backup_file, 'w', encoding='utf-8') as bf:
                json.dump(intents_data, bf, indent=2)
        
        # Group improvements by topic
        grouped = improvements_df.groupby('topic')
        updates_count = 0
        new_topics_count = 0
        
        for topic, group in grouped:
            # Find matching intent or create new one
            intent_found = False
            for intent in intents_data["intents"]:
                if intent["tag"] == topic:
                    # Update existing responses and patterns
                    new_responses = group['improved_response'].unique().tolist()
                    new_patterns = group['query'].unique().tolist()
                    
                    # Add only new responses
                    for resp in new_responses:
                        if resp not in intent["responses"]:
                            intent["responses"].append(resp)
                            updates_count += 1
                    
                    # Add only new patterns
                    for pattern in new_patterns:
                        if pattern not in intent["patterns"]:
                            intent["patterns"].append(pattern)
                    
                    intent_found = True
                    break
            
            if not intent_found:
                # Create new intent
                new_intent = {
                    "tag": topic,
                    "patterns": group['query'].unique().tolist(),
                    "responses": group['improved_response'].unique().tolist()
                }
                intents_data["intents"].append(new_intent)
                updates_count += len(new_intent["responses"])
                new_topics_count += 1
        
        # Save updated intents file
        with open(intents_file_path, 'w', encoding='utf-8') as f:
            json.dump(intents_data, f, indent=2)
        
        # Try to reload the original model
        try:
            reload_success = initialize_original_model()
            reload_message = "Reloaded original model successfully" if reload_success else "Failed to reload original model"
            logger.info(reload_message)
        except Exception as reload_error:
            logger.error(f"Error reloading original model: {str(reload_error)}")
            reload_message = f"Error reloading original model: {str(reload_error)}"
        
        return {
            "original_updated": True,
            "original_updates_count": updates_count,
            "new_topics_count": new_topics_count,
            "backup_file": backup_file,
            "reload_message": reload_message
        }
    
    except Exception as e:
        logger.error(f"Error updating original model: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"original_error": str(e), "original_updated": False}

def export_positive_examples(output_path=None):
    """
    Export positive feedback examples to a CSV file for retraining
    
    Args:
        output_path (str, optional): Path to save the CSV file. If None, a default path is used.
        
    Returns:
        dict: Results of the export process including path to the exported file
    """
    try:
        # Create default output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_dir = os.path.join(current_app.instance_path, 'exports')
            os.makedirs(export_dir, exist_ok=True)
            output_path = os.path.join(export_dir, f'positive_examples_{timestamp}.csv')
        
        # Query for chats with positive feedback
        positive_chats = list(mongo.db.chats.aggregate([
            {
                "$lookup": {
                    "from": "feedback",
                    "localField": "_id",
                    "foreignField": "chat_id",
                    "as": "feedback"
                }
            },
            {
                "$match": {
                    "feedback": {"$exists": True, "$ne": []},
                    "$or": [
                        {"feedback.was_helpful": True},
                        {"feedback.rating": {"$gte": 4}}
                    ]
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "message": 1,
                    "response": 1,
                    "model_used": 1,
                    "topic": 1,
                    "conversation_context.topic": 1,
                    "rating": {"$arrayElemAt": ["$feedback.rating", 0]},
                    "was_helpful": {"$arrayElemAt": ["$feedback.was_helpful", 0]},
                    "timestamp": 1
                }
            }
        ]))
        
        # Prepare CSV data
        data = []
        for chat in positive_chats:
            # Determine topic from either direct field or conversation context
            topic = chat.get("topic", "unknown")
            if topic == "unknown" and "conversation_context" in chat and chat["conversation_context"]:
                topic = chat["conversation_context"].get("topic", "unknown")
            
            data.append({
                "id": str(chat["_id"]),
                "query": chat["message"],
                "response": chat["response"],
                "topic": topic,
                "model": chat.get("model_used", "unknown"),
                "rating": chat.get("rating", 0),
                "was_helpful": chat.get("was_helpful", False),
                "timestamp": chat.get("timestamp", datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
            })
        
        # Write to CSV
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False)
        
        # Log the export action
        mongo.db.admin_logs.insert_one({
            "action": "export_positive_examples",
            "timestamp": datetime.now(timezone.utc),
            "admin_id": session.get("user", "unknown"),  # Changed here
            "count": len(data),
            "file_path": output_path
        })
        
        logger.info(f"Exported {len(data)} positive examples to {output_path}")
        
        return {
            "success": True,
            "count": len(data),
            "path": output_path
        }
    
    except Exception as e:
        logger.error(f"Error exporting positive examples: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

def export_problem_cases(output_path=None):
    """
    Export problem cases to a CSV file for improvement
    
    Args:
        output_path (str, optional): Path to save the CSV file. If None, a default path is used.
        
    Returns:
        dict: Results of the export process including path to the exported file
    """
    try:
        # Create default output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_dir = os.path.join(current_app.instance_path, 'exports')
            os.makedirs(export_dir, exist_ok=True)
            output_path = os.path.join(export_dir, f'problem_cases_{timestamp}.csv')
        
        # Query for chats with negative feedback
        negative_chats = list(mongo.db.chats.aggregate([
            {
                "$lookup": {
                    "from": "feedback",
                    "localField": "_id",
                    "foreignField": "chat_id",
                    "as": "feedback"
                }
            },
            {
                "$match": {
                    "feedback": {"$exists": True, "$ne": []},
                    "$or": [
                        {"feedback.was_helpful": False},
                        {"feedback.rating": {"$lt": 3}}
                    ]
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "message": 1,
                    "response": 1,
                    "model_used": 1,
                    "topic": 1,
                    "conversation_context.topic": 1,
                    "rating": {"$arrayElemAt": ["$feedback.rating", 0]},
                    "was_helpful": {"$arrayElemAt": ["$feedback.was_helpful", 0]},
                    "feedback_text": {"$arrayElemAt": ["$feedback.feedback_text", 0]},
                    "timestamp": 1
                }
            }
        ]))
        
        # Prepare CSV data
        data = []
        for chat in negative_chats:
            # Determine topic from either direct field or conversation context
            topic = chat.get("topic", "unknown")
            if topic == "unknown" and "conversation_context" in chat and chat["conversation_context"]:
                topic = chat["conversation_context"].get("topic", "unknown")
            
            data.append({
                "id": str(chat["_id"]),
                "query": chat["message"],
                "current_response": chat["response"],
                "topic": topic,
                "model": chat.get("model_used", "unknown"),
                "rating": chat.get("rating", 0),
                "was_helpful": chat.get("was_helpful", False),
                "feedback": chat.get("feedback_text", ""),
                "improved_response": "",  # Empty column for admins to fill in
                "timestamp": chat.get("timestamp", datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
            })
        
        # Write to CSV
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False)
        
        # Log the export action
        mongo.db.admin_logs.insert_one({
            "action": "export_problem_cases",
            "timestamp": datetime.now(timezone.utc),
            "admin_id": session.get("user", "unknown"),  # Changed here
            "count": len(data),
            "file_path": output_path
        })
        
        logger.info(f"Exported {len(data)} problem cases to {output_path}")
        
        return {
            "success": True,
            "count": len(data),
            "path": output_path
        }
    
    except Exception as e:
        logger.error(f"Error exporting problem cases: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}