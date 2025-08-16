"""
Chatbot service for processing user messages using Claude API.
"""
import uuid
import anthropic
from datetime import datetime, timezone
from flask import current_app
from wellbeing.models.chat import create_chat, get_previous_message

# Crisis keywords for detection - expanded list
CRISIS_KEYWORDS = [
    'suicide', 'kill myself', 'end my life', 'want to die', 'hurt myself',
    'self harm', 'no point living', 'better off dead', 'ending it all',
    'don\'t want to live', 'cutting', 'overdose', 'jump off', 'hang myself',
    'self-harm', 'self-injury', 'suicidal thoughts', 'suicidal ideation'
]

def check_for_crisis(message):
    """Check if message contains crisis-related content."""
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in CRISIS_KEYWORDS)

def get_crisis_response():
    """Get appropriate crisis response."""
    crisis_message = current_app.config.get('CRISIS_RESPONSE_MESSAGE', 
        """🚨 I'm very concerned about what you've shared. Please reach out for immediate help:
        
        📞 Crisis Hotline: 988 (Kenya Suicide & Crisis Lifeline)
        🚨 Emergency: 911
        🏥 Campus Counseling: [Contact your university counseling center]
        💬 Crisis Text Line: Text HOME to 741741
        
        You matter and help is available. Please don't hesitate to reach out."""
    )
    
    return {
        "response": crisis_message,
        "confidence": 1.0,
        "topic": "crisis"
    }
def get_claude_response(user_input, previous_context=None):
    """
    Get response from Claude API.
    
    Args:
        user_input (str): User message
        previous_context (dict): Previous conversation context
        
    Returns:
        dict: Response data
    """
    try:
        # Set up Claude client
        client = anthropic.Anthropic(api_key=current_app.config.get('CLAUDE_API_KEY'))
        
        # FORCE SHORT RESPONSES - ABSOLUTELY NO FORMATTING
        system_prompt = """You are a compassionate university mental health assistant. Rules:
- Always start with empathy and validation
- Response length should fit the situation:
  • Short and warm for greetings, mood check-ins, or quick follow-ups
  • Longer (200–350 words) ONLY when sharing multiple strategies
- If giving multiple strategies, format as:
  • Each strategy starts with a bullet symbol '•'
  • Each bullet is short and actionable
  • Each bullet on its own 
  
- If a student expresses ongoing distress, overwhelm, or complex issues, gently suggest connecting with a therapist
- Mention that the system can auto-match them to a therapist and schedule a Zoom session easily

- NEVER use asterisks (*) or any special formatting
- Avoid unnecessary length; be supportive and clear
- End longer strategy responses with an encouraging note or a reflective question


FORBIDDEN: Never use * _ ** __ or any formatting symbols except bullet points."""

        # Add debug logging
        current_app.logger.info("FORCING BULLET POINT FORMAT")
        
        # Build conversation messages
        messages = []
        
        # Add previous context if available
        if previous_context and previous_context.get('message') and previous_context.get('response'):
            messages.extend([
                {"role": "user", "content": previous_context['message']},
                {"role": "assistant", "content": previous_context['response']}
            ])
        
        # Add current user message
        messages.append({"role": "user", "content": user_input})
        
        # Get correct model and max_tokens from config
        model = current_app.config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        max_tokens = current_app.config.get('CLAUDE_MAX_TOKENS', 600)  # UPDATED DEFAULT
        temperature = current_app.config.get('CLAUDE_TEMPERATURE', 0.7)
        
        current_app.logger.info(f"Using model: {model}, max_tokens: {max_tokens}")
        
        # Make API call to Claude
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages
        )
        
        # Post-process response to remove ALL asterisks and fix bullet formatting
        ai_response = response.content[0].text.strip()
        
        # AGGRESSIVELY remove ALL asterisks and formatting characters
        ai_response = ai_response.replace('**', '')  # Remove double asterisks
        ai_response = ai_response.replace('*', '')   # Remove single asterisks
        ai_response = ai_response.replace('__', '')  # Remove underscores
        ai_response = ai_response.replace('_', '')   # Remove single underscores
        
        # Clean up any extra spaces left by removed formatting
        import re
        ai_response = re.sub(r'\s+', ' ', ai_response)  # Replace multiple spaces with single space
        ai_response = re.sub(r'^\s+', '', ai_response, flags=re.MULTILINE)  # Remove leading spaces on lines
        
        # Convert bullet points to proper line breaks if Claude didn't format them correctly
        if '•' in ai_response and '\n•' not in ai_response:
            # Replace • with line break + • to ensure vertical formatting
            ai_response = ai_response.replace('• ', '\n• ')
            # Clean up any double line breaks
            ai_response = ai_response.replace('\n\n• ', '\n• ')
            # Ensure we start clean if the first character is a bullet
            if ai_response.startswith('\n• '):
                ai_response = ai_response[1:]  # Remove leading newline
        
        # Final cleanup
        ai_response = ai_response.strip()
        
        # Log response length for debugging
        current_app.logger.info(f"Response length: {len(ai_response)} characters, {len(ai_response.split())} words")
        current_app.logger.info(f"Response preview: {ai_response[:150]}...")
        
        # Classify topic based on keywords in user input
        topic = classify_topic(user_input)
        
        # Calculate token usage for cost tracking
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        total_tokens = input_tokens + output_tokens
        
        # Log token usage for budget tracking
        current_app.logger.info(f"Claude API usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
        
        return {
            "response": ai_response,
            "confidence": 0.9,  # Claude doesn't provide confidence scores
            "model": f"claude-{model}",
            "topic": topic,
            "tokens_used": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
        
    except anthropic.APIError as e:
        current_app.logger.error(f"Claude API error: {str(e)}")
        return {
            "response": "I'm experiencing technical difficulties. Please try again in a moment.",
            "confidence": 0.0,
            "model": "error-claude",
            "topic": "error",
            "tokens_used": 0
        }
    except anthropic.RateLimitError as e:
        current_app.logger.error(f"Claude rate limit exceeded: {str(e)}")
        return {
            "response": "I'm currently receiving many messages. Please wait a moment and try again.",
            "confidence": 0.0,
            "model": "rate-limit-claude",
            "topic": "error",
            "tokens_used": 0
        }
    except anthropic.AuthenticationError as e:
        current_app.logger.error(f"Claude authentication error: {str(e)}")
        return {
            "response": "I'm having authentication issues. Please contact support.",
            "confidence": 0.0,
            "model": "auth-error-claude",
            "topic": "error",
            "tokens_used": 0
        }
    except Exception as e:
        current_app.logger.error(f"Error getting Claude response: {str(e)}")
        return {
            "response": "I'm having trouble processing your message. Could you try rephrasing?",
            "confidence": 0.0,
            "model": "error-fallback",
            "topic": "error",
            "tokens_used": 0
        }



def classify_topic(user_input):
    """
    Enhanced keyword-based topic classification for university students.
    
    Args:
        user_input (str): User message
        
    Returns:
        str: Classified topic
    """
    user_input_lower = user_input.lower()
    
    topic_keywords = {
        'anxiety': ['anxious', 'anxiety', 'worried', 'panic', 'nervous', 'fear', 'panic attack'],
        'depression': ['depressed', 'depression', 'sad', 'hopeless', 'empty', 'lonely', 'worthless'],
        'stress': ['stressed', 'stress', 'overwhelmed', 'pressure', 'burden', 'burnout'],
        'sleep': ['sleep', 'insomnia', 'tired', 'exhausted', 'rest', 'fatigue', 'can\'t sleep'],
        'relationships': ['relationship', 'partner', 'family', 'friends', 'social', 'dating', 'breakup'],
        'academic': ['study', 'exam', 'grades', 'school', 'university', 'assignment', 'homework', 'test'],
        'work': ['work', 'job', 'career', 'boss', 'workplace', 'office', 'internship'],
        'coping': ['cope', 'coping', 'manage', 'handle', 'deal with', 'strategies'],
        'therapy': ['therapy', 'therapist', 'counseling', 'professional help', 'counselor'],
        'self_esteem': ['confidence', 'self-worth', 'self-esteem', 'insecure', 'inadequate'],
        'eating': ['eating', 'food', 'weight', 'body image', 'appetite', 'diet'],
        'substance': ['alcohol', 'drinking', 'drugs', 'substance', 'addiction', 'smoking'],
        'trauma': ['trauma', 'ptsd', 'abuse', 'assault', 'violence', 'flashbacks']
    }
    
    # Check for each topic's keywords
    for topic, keywords in topic_keywords.items():
        if any(keyword in user_input_lower for keyword in keywords):
            return topic
    
    return 'general_support'

def estimate_cost(input_tokens, output_tokens, model_name):
    """
    Estimate the cost of a Claude API call.
    
    Args:
        input_tokens (int): Number of input tokens
        output_tokens (int): Number of output tokens
        model_name (str): Claude model name
        
    Returns:
        float: Estimated cost in USD
    """
    # Updated pricing for Claude 4 models
    if 'sonnet-4' in model_name:
        input_cost = (input_tokens / 1_000_000) * 3.0
        output_cost = (output_tokens / 1_000_000) * 15.0
        return input_cost + output_cost
    elif 'opus-4' in model_name:
        input_cost = (input_tokens / 1_000_000) * 15.0
        output_cost = (output_tokens / 1_000_000) * 75.0
        return input_cost + output_cost
    elif '3-5-sonnet' in model_name or '3.5-sonnet' in model_name:
        # Claude 3.5 Sonnet pricing (cheaper option)
        input_cost = (input_tokens / 1_000_000) * 3.0
        output_cost = (output_tokens / 1_000_000) * 15.0
        return input_cost + output_cost
    
    # Default to Haiku pricing if model not found
    input_cost = (input_tokens / 1_000_000) * 0.25
    output_cost = (output_tokens / 1_000_000) * 1.25
    return input_cost + output_cost

def check_budget_limits(estimated_cost):
    """
    Check if the estimated cost would exceed budget limits.
    
    Args:
        estimated_cost (float): Estimated cost in USD
        
    Returns:
        bool: True if within budget, False if would exceed
    """
    daily_limit = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)  # UPDATED DEFAULT
    monthly_limit = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)   # UPDATED DEFAULT
    
    # In a real implementation, you'd check against actual daily/monthly spending
    # For now, just check if single request exceeds reasonable limits
    if estimated_cost > daily_limit / 10:  # Single request shouldn't be more than 10% of daily limit
        current_app.logger.warning(f"High cost request: ${estimated_cost:.4f}")
        return False
    
    return True

def process_message(user_id, user_input):
    """
    Process a user message and generate a response using Claude API.
    
    Args:
        user_id (str): User ID
        user_input (str): User message
        
    Returns:
        dict: Response data including text, confidence, and chat ID
    """
    # Record start time to calculate response time
    start_time = datetime.now()
    
    # Default values in case of errors
    response = "I'm having trouble understanding. Could you rephrase your question?"
    confidence = 0.0
    model_used = "error-fallback"
    detected_intent = "unknown"
    topic = "unknown"
    tokens_used = 0
    estimated_cost = 0.0
    
    try:
        # Check for crisis content first
        if check_for_crisis(user_input):
            crisis_response = get_crisis_response()
            response = crisis_response["response"]
            confidence = crisis_response["confidence"]
            model_used = "crisis_detection"
            detected_intent = "crisis"
            topic = "crisis"
            tokens_used = 0  # Crisis detection doesn't use API
            estimated_cost = 0.0
        else:
            # Get previous context for better responses
            previous_context = get_previous_message(user_id)
            
            # Use Claude API
            claude_response = get_claude_response(user_input, previous_context)
            response = claude_response["response"]
            confidence = claude_response["confidence"]
            model_used = claude_response["model"]
            detected_intent = claude_response.get("topic", "general_support")
            topic = claude_response.get("topic", "general_support")
            tokens_used = claude_response.get("tokens_used", 0)
            
            # Calculate estimated cost
            input_tokens = claude_response.get("input_tokens", 0)
            output_tokens = claude_response.get("output_tokens", 0)
            model_name = current_app.config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
            estimated_cost = estimate_cost(input_tokens, output_tokens, model_name)
            
            # Log cost for monitoring
            current_app.logger.info(f"Request cost: ${estimated_cost:.6f} (Input: {input_tokens}, Output: {output_tokens})")
            
    except Exception as model_error:
        current_app.logger.error(f"Error processing message: {str(model_error)}")
        # Keep the default error values set above
        topic = "error"
    
    # Calculate response time
    response_time = (datetime.now() - start_time).total_seconds() * 1000  # in milliseconds
    
    # Get or create session ID
    session_id = str(uuid.uuid4())
    
    # Store the chat in the database
    chat_id = create_chat(
        user_id=user_id,
        message=user_input,
        response=response,
        confidence=confidence,
        model_used=model_used,
        topic=topic,
        session_id=session_id,
        tokens_used=tokens_used,
        estimated_cost=estimated_cost,
        input_tokens=claude_response.get("input_tokens", 0) if 'claude_response' in locals() else 0,
        output_tokens=claude_response.get("output_tokens", 0) if 'claude_response' in locals() else 0,
        response_time_ms=response_time,
        detected_intent=detected_intent
    )
    
    # Return the response data
    return {
        "response": response,
        "confidence": float(confidence),
        "model": model_used,
        "chat_id": chat_id,
        "detected_intent": detected_intent,
        "response_time_ms": response_time,
        "tokens_used": tokens_used,
        "estimated_cost": estimated_cost
    }