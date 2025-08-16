from datetime import datetime, timezone, time, timedelta
from bson.objectid import ObjectId
from flask import render_template, redirect, url_for, request, flash, jsonify, session, Response
from wellbeing.blueprints.tracking import tracking_bp
from wellbeing.utils.decorators import login_required, csrf_protected
from wellbeing import mongo, logger
from wellbeing.models.user import find_user_by_id
from collections import Counter
from io import StringIO
import csv

# ===================================
# DATETIME UTILITY FUNCTIONS
# ===================================

def ensure_timezone_aware(dt):
    """Ensure datetime object is timezone-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def get_date_range_today():
    """Get start and end of today in UTC."""
    now_utc = datetime.now(timezone.utc)
    today_start = datetime.combine(now_utc.date(), time.min).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(now_utc.date(), time.max).replace(tzinfo=timezone.utc)
    return today_start, today_end

# ===================================
# HELPER FUNCTIONS - MOOD TRACKING
# ===================================

def calculate_mood_streak(user_id):
    """Calculate consecutive days of mood tracking."""
    try:
        moods = list(mongo.db.moods.find(
            {"user_id": user_id}
        ).sort("timestamp", -1))
        
        if not moods:
            return 0
        
        streak = 0
        current_date = datetime.now(timezone.utc).date()
        
        for i in range(30):  # Check last 30 days max
            check_date = current_date - timedelta(days=i)
            
            has_mood = any(
                ensure_timezone_aware(mood['timestamp']).date() == check_date 
                for mood in moods
            )
            
            if has_mood:
                streak += 1
            else:
                if check_date == current_date:
                    continue
                else:
                    break
        
        return streak
    except Exception as e:
        logger.error(f"Error calculating mood streak: {e}")
        return 0

def generate_mood_insights(user_id):
    """Generate personalized insights based on mood history."""
    try:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        moods = list(mongo.db.moods.find({
            "user_id": user_id,
            "timestamp": {"$gte": thirty_days_ago}
        }).sort("timestamp", -1))
        
        insights = []
        
        if len(moods) < 3:
            return [{
                'title': 'Keep Going!',
                'description': 'Track a few more days to unlock insights',
                'icon': 'fas fa-seedling',
                'color': 'text-green-400'
            }]
        
        # Weekly trend analysis
        recent_week = moods[:7]
        older_week = moods[7:14] if len(moods) > 7 else []
        
        if recent_week and older_week:
            recent_positive = sum(1 for m in recent_week if m['mood'] in ['happy', 'energetic'])
            older_positive = sum(1 for m in older_week if m['mood'] in ['happy', 'energetic'])
            
            if recent_positive > older_positive:
                insights.append({
                    'title': 'Improving Trend',
                    'description': 'Your mood is getting better! 📈',
                    'icon': 'fas fa-chart-line',
                    'color': 'text-green-400'
                })
        
        # Best day analysis
        day_moods = {}
        for mood in moods:
            mood_timestamp = ensure_timezone_aware(mood['timestamp'])
            day_name = mood_timestamp.strftime('%A')
            if day_name not in day_moods:
                day_moods[day_name] = []
            day_moods[day_name].append(mood['mood'])
        
        best_day = None
        best_ratio = 0
        for day, day_mood_list in day_moods.items():
            if len(day_mood_list) >= 2:
                positive = sum(1 for m in day_mood_list if m in ['happy', 'energetic'])
                ratio = positive / len(day_mood_list)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_day = day
        
        if best_day and best_ratio > 0.6:
            insights.append({
                'title': 'Best Day Pattern',
                'description': f'You feel great on {best_day}s! ✨',
                'icon': 'fas fa-calendar-day',
                'color': 'text-purple-400'
            })
        
        # Trigger analysis
        all_triggers = []
        for mood in moods:
            if mood.get('triggers'):
                all_triggers.extend(mood['triggers'])
        
        if all_triggers:
            trigger_counts = Counter(all_triggers)
            top_trigger = trigger_counts.most_common(1)[0]
            
            trigger_moods = []
            for mood in moods:
                if mood.get('triggers') and top_trigger[0] in mood['triggers']:
                    trigger_moods.append(mood['mood'])
            
            if trigger_moods:
                positive_count = sum(1 for m in trigger_moods if m in ['happy', 'energetic'])
                ratio = positive_count / len(trigger_moods)
                
                if ratio > 0.7:
                    insights.append({
                        'title': 'Positive Trigger',
                        'description': f'{top_trigger[0].title()} boosts your mood! 🌟',
                        'icon': 'fas fa-lightbulb',
                        'color': 'text-yellow-400'
                    })
        
        if not insights:
            insights.append({
                'title': 'Building Patterns',
                'description': 'Keep tracking to discover your mood patterns!',
                'icon': 'fas fa-puzzle-piece',
                'color': 'text-blue-400'
            })
        
        return insights[:3]
        
    except Exception as e:
        logger.error(f"Error generating mood insights: {e}")
        return []

def format_mood_history(moods):
    """Format mood data for display."""
    try:
        formatted = []
        for mood in moods:
            triggers = mood.get('triggers', [])
            if isinstance(triggers, str):
                triggers = [t.strip() for t in triggers.split(',') if t.strip()]
            
            # Ensure timestamp is timezone-aware
            timestamp = ensure_timezone_aware(mood['timestamp'])
            
            formatted_mood = {
                'mood': mood['mood'],
                'intensity': mood.get('intensity', 5),
                'triggers': triggers,
                'context': mood.get('context', ''),
                'timestamp': timestamp,
                'formatted_date': timestamp.strftime('%B %d, %Y'),
                'day_number': timestamp.strftime('%d').lstrip('0')
            }
            formatted.append(formatted_mood)
        
        return formatted
    except Exception as e:
        logger.error(f"Error formatting mood history: {e}")
        return []

# ===================================
# HELPER FUNCTIONS - JOURNALING
# ===================================

def calculate_journal_streak(user_id):
    """Calculate consecutive days of journaling."""
    try:
        journals = list(mongo.db.journals.find(
            {"user_id": user_id}
        ).sort("created_at", -1))
        
        if not journals:
            return 0
        
        streak = 0
        current_date = datetime.now(timezone.utc).date()
        
        for i in range(30):
            check_date = current_date - timedelta(days=i)
            
            has_journal = any(
                ensure_timezone_aware(journal['created_at']).date() == check_date 
                for journal in journals
            )
            
            if has_journal:
                streak += 1
            else:
                if check_date == current_date:
                    continue
                else:
                    break
        
        return streak
    except Exception as e:
        logger.error(f"Error calculating journal streak: {e}")
        return 0

def generate_journal_insights(user_id):
    """Generate insights based on journaling patterns."""
    try:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        journals = list(mongo.db.journals.find({
            "user_id": user_id,
            "created_at": {"$gte": thirty_days_ago}
        }).sort("created_at", -1))
        
        insights = []
        
        if len(journals) < 3:
            return [{
                'title': 'Start Writing',
                'description': 'Write a few more entries to unlock insights!',
                'icon': 'fas fa-pen-fancy',
                'color': 'text-blue-400'
            }]
        
        # Writing frequency analysis
        total_days = 30
        writing_days = len(set(j['created_at'].date() for j in journals))
        frequency_rate = writing_days / total_days
        
        if frequency_rate > 0.8:
            insights.append({
                'title': 'Consistent Writer',
                'description': 'You\'re building a strong writing habit! 📝',
                'icon': 'fas fa-medal',
                'color': 'text-yellow-400'
            })
        elif frequency_rate > 0.5:
            insights.append({
                'title': 'Good Progress',
                'description': 'Keep up the regular writing routine!',
                'icon': 'fas fa-chart-line',
                'color': 'text-green-400'
            })
        
        # Content length analysis
        content_lengths = [len(j.get('content', '')) for j in journals]
        avg_length = sum(content_lengths) / len(content_lengths) if content_lengths else 0
        
        if avg_length > 500:
            insights.append({
                'title': 'Detailed Reflector',
                'description': 'You write thoughtful, detailed entries',
                'icon': 'fas fa-scroll',
                'color': 'text-purple-400'
            })
        
        # Gratitude analysis
        gratitude_entries = [j for j in journals if j.get('gratitude')]
        gratitude_rate = len(gratitude_entries) / len(journals) if journals else 0
        
        if gratitude_rate > 0.6:
            insights.append({
                'title': 'Gratitude Champion',
                'description': 'You regularly practice gratitude! 🙏',
                'icon': 'fas fa-heart',
                'color': 'text-pink-400'
            })
        
        return insights[:3]
        
    except Exception as e:
        logger.error(f"Error generating journal insights: {e}")
        return []

# ===================================
# HELPER FUNCTIONS - GOALS
# ===================================

def get_category_emoji(category):
    """Get emoji for goal category."""
    emoji_map = {
        'mindfulness': '🧘',
        'fitness': '💪',
        'sleep': '😴',
        'nutrition': '🥗',
        'social': '👥',
        'learning': '📚',
        'creative': '🎨',
        'other': '✨'
    }
    return emoji_map.get(category, '✨')

def calculate_wellness_score(user_id):
    """Calculate overall wellness score based on all activities."""
    try:
        mood_score = calculate_mood_score(user_id)
        journal_score = calculate_journal_score(user_id)
        goals_score = calculate_goals_score(user_id)
        
        wellness_score = int((mood_score * 0.4) + (journal_score * 0.3) + (goals_score * 0.3))
        
        return {
            'wellness_score': wellness_score,
            'mood_score': mood_score,
            'journal_score': journal_score,
            'goals_score': goals_score
        }
    except Exception as e:
        logger.error(f"Error calculating wellness score: {e}")
        return {
            'wellness_score': 0,
            'mood_score': 0,
            'journal_score': 0,
            'goals_score': 0
        }

def calculate_mood_score(user_id):
    """Calculate mood score based on recent tracking."""
    try:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        moods = list(mongo.db.moods.find({
            "user_id": user_id,
            "timestamp": {"$gte": week_ago}
        }))
        
        if not moods:
            return 0
        
        consistency_score = min(len(moods) * 15, 70)
        positive_moods = sum(1 for m in moods if m['mood'] in ['happy', 'energetic'])
        quality_score = (positive_moods / len(moods)) * 30 if moods else 0
        
        return int(consistency_score + quality_score)
    except Exception as e:
        logger.error(f"Error calculating mood score: {e}")
        return 0

def calculate_journal_score(user_id):
    """Calculate journal score based on consistency."""
    try:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        journals = list(mongo.db.journals.find({
            "user_id": user_id,
            "created_at": {"$gte": week_ago}
        }))
        
        if not journals:
            return 0
        
        entry_score = min(len(journals) * 20, 80)
        gratitude_entries = sum(1 for j in journals if j.get('gratitude'))
        gratitude_bonus = min(gratitude_entries * 5, 20)
        
        return int(entry_score + gratitude_bonus)
    except Exception as e:
        logger.error(f"Error calculating journal score: {e}")
        return 0

def calculate_goals_score(user_id):
    """Calculate goals score based on completion rate."""
    try:
        goals = list(mongo.db.goals.find({
            "user_id": user_id,
            "status": {"$ne": "deleted"}
        }))
        
        if not goals:
            return 0
        
        total_progress = 0
        for goal in goals:
            progress_ratio = min(goal.get('progress', 0) / goal.get('target', 1), 1.0)
            total_progress += progress_ratio
        
        average_progress = total_progress / len(goals) if goals else 0
        return int(average_progress * 100)
    except Exception as e:
        logger.error(f"Error calculating goals score: {e}")
        return 0

def generate_personalized_recommendations(user_id):
    """Generate personalized recommendations based on user patterns."""
    try:
        recommendations = []
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Check mood tracking
        recent_moods = list(mongo.db.moods.find({
            "user_id": user_id,
            "timestamp": {"$gte": week_ago}
        }))
        
        if len(recent_moods) < 5:
            recommendations.append({
                'title': 'Track Your Mood Daily',
                'description': 'Consistent mood tracking helps identify patterns',
                'icon': 'fas fa-smile',
                'color': 'text-green-400',
                'action': 'goToMoodTracking()',
                'action_text': 'Track Now'
            })
        
        # Check for negative mood patterns
        if recent_moods:
            negative_moods = sum(1 for m in recent_moods if m['mood'] in ['sad', 'anxious'])
            if negative_moods > len(recent_moods) * 0.6:
                recommendations.append({
                    'title': 'Consider Self-Care',
                    'description': 'You\'ve had some challenging days. Try meditation or talking to someone',
                    'icon': 'fas fa-heart',
                    'color': 'text-pink-400',
                    'action': 'goToResources()',
                    'action_text': 'Get Help'
                })
        
        # Check journaling
        recent_journals = list(mongo.db.journals.find({
            "user_id": user_id,
            "created_at": {"$gte": week_ago}
        }))
        
        if len(recent_journals) < 3:
            recommendations.append({
                'title': 'Try Journaling',
                'description': 'Writing helps process emotions and reduce stress',
                'icon': 'fas fa-pen',
                'color': 'text-blue-400',
                'action': 'goToJournal()',
                'action_text': 'Start Writing'
            })
        
        # Check goals
        active_goals = list(mongo.db.goals.find({
            "user_id": user_id,
            "status": {"$ne": "deleted"}
        }))
        
        if len(active_goals) == 0:
            recommendations.append({
                'title': 'Set Wellness Goals',
                'description': 'Goals give direction and motivation to your wellness journey',
                'icon': 'fas fa-bullseye',
                'color': 'text-purple-400',
                'action': 'goToGoals()',
                'action_text': 'Set Goals'
            })
        
        return recommendations[:3]
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return []

# ===================================
# MAIN ROUTES
# ===================================

@tracking_bp.route('/tracking')
@login_required
def index():
    """Enhanced main tracking page with all sections."""
    try:
        user_id = str(session['user'])
        user = find_user_by_id(ObjectId(user_id))
        
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        settings = user.get('settings', {})
        
        # ===== MOOD DATA =====
        # Get current date in UTC
        today_start, today_end = get_date_range_today()
        
        today_mood = mongo.db.moods.find_one({
            "user_id": user_id,
            "timestamp": {"$gte": today_start, "$lte": today_end}
        })
        
        user_already_tracked_mood_today = today_mood is not None
        
        if today_mood:
            today_mood['date'] = today_mood['timestamp'].strftime('%b %d')
            if 'triggers' in today_mood and isinstance(today_mood['triggers'], str):
                today_mood['triggers'] = [t.strip() for t in today_mood['triggers'].split(',') if t.strip()]
        
        mood_streak = calculate_mood_streak(user_id)
        mood_history_raw = list(mongo.db.moods.find(
            {"user_id": user_id}
        ).sort("timestamp", -1).limit(30))
        mood_history = format_mood_history(mood_history_raw)
        mood_insights = generate_mood_insights(user_id)
        
        # ===== JOURNAL DATA =====
        today_journal = mongo.db.journals.find_one({
            "user_id": user_id,
            "created_at": {"$gte": today_start, "$lte": today_end}
        })
        
        user_already_journaled_today = today_journal is not None
        
        if today_journal:
            if 'gratitude' in today_journal and isinstance(today_journal['gratitude'], list):
                today_journal['gratitude'] = [item for item in today_journal['gratitude'] if item.strip()]
        
        journal_streak = calculate_journal_streak(user_id)
        journal_entries_raw = list(mongo.db.journals.find(
            {"user_id": user_id}
        ).sort("created_at", -1).limit(10))
        
        journal_entries = []
        for entry in journal_entries_raw:
            created_at = ensure_timezone_aware(entry['created_at'])
            formatted_entry = {
                '_id': entry['_id'],
                'title': entry.get('title', 'Untitled'),
                'content': entry.get('content', ''),
                'gratitude': entry.get('gratitude', []),
                'created_at': created_at,
                'formatted_date': created_at.strftime('%B %d, %Y')
            }
            journal_entries.append(formatted_entry)
        
        journal_insights = generate_journal_insights(user_id)
        
        # ===== GOALS DATA =====
        active_goals_raw = list(mongo.db.goals.find({
            "user_id": user_id,
            "status": {"$ne": "deleted"}
        }).sort("created_at", -1))
        
        active_goals = []
        for goal in active_goals_raw:
            formatted_goal = {
                '_id': goal['_id'],
                'description': goal.get('description', ''),
                'category': goal.get('category', 'other'),
                'category_emoji': get_category_emoji(goal.get('category', 'other')),
                'target': goal.get('target', 1),
                'progress': goal.get('progress', 0),
                'unit': goal.get('unit', 'times'),
                'timeframe': goal.get('timeframe', 'week'),
                'created_at': goal.get('created_at', datetime.now(timezone.utc))
            }
            active_goals.append(formatted_goal)
        
        # Goal categories summary
        goal_categories = []
        category_counts = Counter(goal.get('category', 'other') for goal in active_goals_raw)
        for category, count in category_counts.items():
            completed = sum(1 for g in active_goals_raw 
                          if g.get('category') == category and g.get('progress', 0) >= g.get('target', 1))
            completion_rate = (completed / count * 100) if count > 0 else 0
            
            goal_categories.append({
                'name': category.title(),
                'emoji': get_category_emoji(category),
                'active_count': count,
                'completion_rate': completion_rate
            })
        
        total_goals_completed = sum(1 for g in active_goals_raw if g.get('progress', 0) >= g.get('target', 1))
        
        # ===== SUMMARY DATA =====
        wellness_scores = calculate_wellness_score(user_id)
        
        # Week summary
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        days_tracked = len(set(
            ensure_timezone_aware(m['timestamp']).date() for m in mongo.db.moods.find({
                "user_id": user_id,
                "timestamp": {"$gte": week_ago}
            })
        ))
        
        # Dominant mood this week
        week_moods = list(mongo.db.moods.find({
            "user_id": user_id,
            "timestamp": {"$gte": week_ago}
        }))
        dominant_mood = 'neutral'
        if week_moods:
            mood_counts = Counter(m['mood'] for m in week_moods)
            dominant_mood = mood_counts.most_common(1)[0][0]
        
        goals_completed_week = sum(1 for g in active_goals_raw 
                                 if ensure_timezone_aware(g.get('updated_at', g.get('created_at', datetime.min.replace(tzinfo=timezone.utc)))) >= week_ago 
                                 and g.get('progress', 0) >= g.get('target', 1))
        
        journal_entries_week = len(list(mongo.db.journals.find({
            "user_id": user_id,
            "created_at": {"$gte": week_ago}
        })))
        
        personalized_recommendations = generate_personalized_recommendations(user_id)
        
        today_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        return render_template(
            'tracking.html',
            user=user,
            settings=settings,
            today_date=today_date,
            
            # Mood data
            user_already_tracked_mood_today=user_already_tracked_mood_today,
            today_mood=today_mood,
            mood_streak=mood_streak,
            mood_history=mood_history,
            mood_insights=mood_insights,
            
            # Journal data
            user_already_journaled_today=user_already_journaled_today,
            today_journal=today_journal,
            journal_streak=journal_streak,
            journal_entries=journal_entries,
            journal_insights=journal_insights,
            
            # Goals data
            active_goals=active_goals,
            goal_categories=goal_categories,
            total_goals_completed=total_goals_completed,
            
            # Summary data
            wellness_score=wellness_scores['wellness_score'],
            mood_score=wellness_scores['mood_score'],
            journal_score=wellness_scores['journal_score'],
            goals_score=wellness_scores['goals_score'],
            days_tracked=days_tracked,
            dominant_mood=dominant_mood,
            goals_completed_week=goals_completed_week,
            journal_entries_week=journal_entries_week,
            personalized_recommendations=personalized_recommendations
        )
        
    except Exception as e:
        logger.error(f"Error in tracking route: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))

# ===================================
# MOOD TRACKING ROUTES
# ===================================

@tracking_bp.route('/track_mood', methods=['POST'])
@login_required
def track_mood_route():
    """Track mood with intensity and triggers - once per day only."""
    try:
        user_id = str(session['user'])
        
        mood = request.form.get('mood')
        intensity = request.form.get('intensity', 5)
        triggers = request.form.get('triggers', '')
        context = request.form.get('context', '')
        
        valid_moods = ['happy', 'neutral', 'sad', 'anxious', 'energetic']
        if not mood or mood not in valid_moods:
            flash('Please select a valid mood.', 'error')
            return redirect(url_for('tracking.index') + '#mood')
        
        try:
            intensity = int(intensity)
            if intensity < 1 or intensity > 10:
                intensity = 5
        except (ValueError, TypeError):
            intensity = 5
        
        trigger_list = []
        if triggers:
            valid_triggers = ['work', 'sleep', 'exercise', 'social', 'weather', 'health', 'family', 'stress']
            trigger_list = [t.strip().lower() for t in triggers.split(',') if t.strip()]
            trigger_list = [t for t in trigger_list if t in valid_triggers][:3]
        
        today_start, today_end = get_date_range_today()
        
        existing_mood = mongo.db.moods.find_one({
            "user_id": user_id,
            "timestamp": {"$gte": today_start, "$lte": today_end}
        })
        
        if existing_mood:
            flash('You already tracked your mood today. Come back tomorrow!', 'warning')
            return redirect(url_for('tracking.index') + '#mood')
        
        mood_entry = {
            "user_id": user_id,
            "mood": mood,
            "intensity": intensity,
            "triggers": trigger_list,
            "context": context.strip()[:100] if context else '',
            "timestamp": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        
        result = mongo.db.moods.insert_one(mood_entry)
        
        if result.inserted_id:
            new_streak = calculate_mood_streak(user_id)
            
            if new_streak > 1:
                flash(f'Mood tracked! 🔥 {new_streak} day streak!', 'success')
            else:
                flash('Mood tracked successfully!', 'success')
        else:
            flash('Error tracking mood. Please try again.', 'error')
        
        return redirect(url_for('tracking.index') + '#mood')
        
    except Exception as e:
        logger.error(f"Error tracking mood: {e}")
        flash('Error tracking mood. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#mood')

# ===================================
# JOURNAL ROUTES
# ===================================

@tracking_bp.route('/save_journal', methods=['POST'])
@login_required
def save_journal():
    """Save a new journal entry."""
    try:
        user_id = str(session['user'])
        
        title = request.form.get('title', '').strip()[:100]
        content = request.form.get('content', '').strip()[:2000]
        gratitude_items = request.form.getlist('gratitude[]')
        
        if not content:
            flash('Please write something in your journal entry.', 'error')
            return redirect(url_for('tracking.index') + '#journal')
        
        today_start, today_end = get_date_range_today()
        
        existing_journal = mongo.db.journals.find_one({
            "user_id": user_id,
            "created_at": {"$gte": today_start, "$lte": today_end}
        })
        
        if existing_journal:
            flash('You\'ve already written in your journal today. Come back tomorrow!', 'warning')
            return redirect(url_for('tracking.index') + '#journal')
        
        gratitude_list = [item.strip()[:100] for item in gratitude_items if item.strip()]
        
        journal_entry = {
            "user_id": user_id,
            "title": title or 'Untitled Entry',
            "content": content,
            "gratitude": gratitude_list,
            "created_at": datetime.now(timezone.utc),
            "word_count": len(content.split())
        }
        
        result = mongo.db.journals.insert_one(journal_entry)
        
        if result.inserted_id:
            new_streak = calculate_journal_streak(user_id)
            if new_streak > 1:
                flash(f'Journal entry saved! ✍️ {new_streak} day writing streak!', 'success')
            else:
                flash('Journal entry saved successfully!', 'success')
        else:
            flash('Error saving journal entry. Please try again.', 'error')
        
        return redirect(url_for('tracking.index') + '#journal')
        
    except Exception as e:
        logger.error(f"Error saving journal entry: {e}")
        flash('Error saving journal entry. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#journal')

@tracking_bp.route('/view_journal/<entry_id>')
@login_required
def view_journal(entry_id):
    """View a specific journal entry."""
    try:
        user_id = str(session['user'])
        
        entry = mongo.db.journals.find_one({
            "_id": ObjectId(entry_id),
            "user_id": user_id
        })
        
        if not entry:
            flash('Journal entry not found.', 'error')
            return redirect(url_for('tracking.index'))
        
        user = find_user_by_id(ObjectId(user_id))
        
        return render_template('view_journal.html', entry=entry, user=user)
        
    except Exception as e:
        logger.error(f"Error viewing journal entry: {e}")
        flash('There was an error viewing the journal entry. Please try again.', 'error')
        return redirect(url_for('tracking.index'))

# ===================================
# GOALS ROUTES
# ===================================

@tracking_bp.route('/add_goal', methods=['POST'])
@login_required
def add_goal():
    """Add a new wellness goal."""
    try:
        user_id = str(session['user'])
        
        description = request.form.get('description', '').strip()[:200]
        category = request.form.get('category', 'other')
        target = int(request.form.get('target', 1))
        unit = request.form.get('unit', 'times')
        timeframe = request.form.get('timeframe', 'week')
        
        if not description:
            flash('Please describe your goal.', 'error')
            return redirect(url_for('tracking.index') + '#goals')
        
        if target <= 0:
            target = 1
        
        goal_entry = {
            "user_id": user_id,
            "description": description,
            "category": category,
            "target": target,
            "progress": 0,
            "unit": unit,
            "timeframe": timeframe,
            "status": "active",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        result = mongo.db.goals.insert_one(goal_entry)
        
        if result.inserted_id:
            flash('Goal created successfully!', 'success')
        else:
            flash('Error creating goal. Please try again.', 'error')
        
        return redirect(url_for('tracking.index') + '#goals')
        
    except Exception as e:
        logger.error(f"Error adding goal: {e}")
        flash('Error creating goal. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#goals')

# ===================================
# API ROUTES
# ===================================

@tracking_bp.route('/api/mood_status')
@login_required
def api_mood_status():
    """Get current mood tracking status."""
    try:
        user_id = str(session['user'])
        
        today_start, today_end = get_date_range_today()
        
        today_mood = mongo.db.moods.find_one({
            "user_id": user_id,
            "timestamp": {"$gte": today_start, "$lte": today_end}
        })
        
        return jsonify({
            'success': True,
            'has_tracked_today': today_mood is not None,
            'streak': calculate_mood_streak(user_id),
            'today_mood': {
                'mood': today_mood.get('mood'),
                'intensity': today_mood.get('intensity'),
                'triggers': today_mood.get('triggers', []),
                'context': today_mood.get('context')
            } if today_mood else None
        })
        
    except Exception as e:
        logger.error(f"Error getting mood status: {e}")
        return jsonify({'success': False, 'error': str(e)})

@tracking_bp.route('/api/update_goal_progress', methods=['POST'])
@login_required
def api_update_goal_progress():
    """Update goal progress via API."""
    try:
        user_id = str(session['user'])
        data = request.get_json()
        
        goal_id = data.get('goal_id')
        increment = int(data.get('increment', 1))
        
        if not goal_id:
            return jsonify({'success': False, 'error': 'Goal ID required'})
        
        goal = mongo.db.goals.find_one({
            "_id": ObjectId(goal_id),
            "user_id": user_id
        })
        
        if not goal:
            return jsonify({'success': False, 'error': 'Goal not found'})
        
        new_progress = max(0, goal.get('progress', 0) + increment)
        goal_completed = new_progress >= goal.get('target', 1)
        
        mongo.db.goals.update_one(
            {"_id": ObjectId(goal_id)},
            {
                "$set": {
                    "progress": new_progress,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        return jsonify({
            'success': True,
            'new_progress': new_progress,
            'goal_completed': goal_completed
        })
        
    except Exception as e:
        logger.error(f"Error updating goal progress: {e}")
        return jsonify({'success': False, 'error': str(e)})

@tracking_bp.route('/api/delete_goal', methods=['POST'])
@login_required
def api_delete_goal():
    """Delete a goal via API."""
    try:
        user_id = str(session['user'])
        data = request.get_json()
        
        goal_id = data.get('goal_id')
        
        if not goal_id:
            return jsonify({'success': False, 'error': 'Goal ID required'})
        
        result = mongo.db.goals.update_one(
            {"_id": ObjectId(goal_id), "user_id": user_id},
            {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc)}}
        )
        
        if result.modified_count > 0:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Goal not found'})
        
    except Exception as e:
        logger.error(f"Error deleting goal: {e}")
        return jsonify({'success': False, 'error': str(e)})

@tracking_bp.route('/api/wellness_summary')
@login_required
def api_wellness_summary():
    """Get wellness summary data."""
    try:
        user_id = str(session['user'])
        
        scores = calculate_wellness_score(user_id)
        recommendations = generate_personalized_recommendations(user_id)
        
        return jsonify({
            'success': True,
            'scores': scores,
            'recommendations': recommendations
        })
        
    except Exception as e:
        logger.error(f"Error getting wellness summary: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ===================================
# UTILITY ROUTES
# ===================================

@tracking_bp.route('/export_mood_data')
@login_required
def export_mood_data():
    """Export mood data as CSV."""
    try:
        user_id = str(session['user'])
        
        moods = list(mongo.db.moods.find(
            {"user_id": user_id}
        ).sort("timestamp", 1))
        
        if not moods:
            flash('No mood data to export.', 'warning')
            return redirect(url_for('tracking.index'))
        
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Date', 'Mood', 'Intensity', 'Triggers', 'Context'])
        
        for mood in moods:
            triggers = mood.get('triggers', [])
            if isinstance(triggers, list):
                triggers_str = ', '.join(triggers)
            else:
                triggers_str = str(triggers) if triggers else ''
            
            writer.writerow([
                mood['timestamp'].strftime('%Y-%m-%d'),
                mood['mood'],
                mood.get('intensity', ''),
                triggers_str,
                mood.get('context', '')
            ])
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=mood_data_{datetime.now().strftime("%Y%m%d")}.csv'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting mood data: {e}")
        flash('Error exporting data. Please try again.', 'error')
        return redirect(url_for('tracking.index'))

# ===================================
# LIST VIEW ROUTE
# ===================================

@tracking_bp.route('/list_view')
@login_required
def list_view():
    """Alternative list view of tracking data."""
    try:
        user_id = str(session['user'])
        user = find_user_by_id(ObjectId(user_id))
        
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        settings = user.get('settings', {})
        
        all_moods = list(mongo.db.moods.find(
            {"user_id": user_id}
        ).sort("timestamp", -1))
        
        all_journals = list(mongo.db.journals.find(
            {"user_id": user_id}
        ).sort("created_at", -1))
        
        all_goals = list(mongo.db.goals.find(
            {"user_id": user_id,
             "status": {"$ne": "deleted"}}
        ).sort("created_at", -1))
        
        return render_template(
            'tracking_list.html',
            user=user,
            moods=all_moods,
            journals=all_journals,
            goals=all_goals,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Error in list view route: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('tracking.index'))

# ===================================
# DEVELOPMENT/TESTING ROUTES
# ===================================

@tracking_bp.route('/reset_today_mood', methods=['POST'])
@login_required
def reset_today_mood():
    """Reset today's mood (development only)."""
    try:
        from flask import current_app
        if not current_app.debug:
            return jsonify({'success': False, 'error': 'Not allowed in production'})
        
        user_id = str(session['user'])
        
        today_start, today_end = get_date_range_today()
        
        result = mongo.db.moods.delete_one({
            "user_id": user_id,
            "timestamp": {"$gte": today_start, "$lte": today_end}
        })
        
        if result.deleted_count > 0:
            flash('Today\'s mood entry reset.', 'info')
            return jsonify({'success': True, 'message': 'Mood reset successfully'})
        else:
            return jsonify({'success': False, 'error': 'No mood entry found for today'})
        
    except Exception as e:
        logger.error(f"Error resetting mood: {e}")
        return jsonify({'success': False, 'error': str(e)})