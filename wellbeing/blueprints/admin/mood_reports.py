
from datetime import datetime, timezone, timedelta
from bson.objectid import ObjectId
from flask import render_template, request, jsonify, flash, redirect, url_for, Response
from collections import Counter, defaultdict
from wellbeing import mongo, logger
from wellbeing.utils.decorators import admin_required
from wellbeing.blueprints.admin import admin_bp  
from io import StringIO
import csv

# ===================================
# MOOD ANALYTICS HELPER FUNCTIONS
# ===================================

def get_mood_analytics_data(date_range='30_days', user_filter=None):
    """Get comprehensive mood analytics data."""
    try:
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        if date_range == '7_days':
            start_date = end_date - timedelta(days=7)
        elif date_range == '30_days':
            start_date = end_date - timedelta(days=30)
        elif date_range == '90_days':
            start_date = end_date - timedelta(days=90)
        elif date_range == '1_year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)  # default
        
        # Build query
        query = {
            "timestamp": {"$gte": start_date, "$lte": end_date}
        }
        
        if user_filter:
            query["user_id"] = user_filter
        
        # Get all mood data
        moods = list(mongo.db.moods.find(query).sort("timestamp", 1))
        
        return analyze_mood_data(moods, start_date, end_date)
        
    except Exception as e:
        logger.error(f"Error getting mood analytics: {e}")
        return get_empty_analytics()

def analyze_mood_data(moods, start_date, end_date):
    """Analyze mood data and return comprehensive insights."""
    try:
        if not moods:
            return get_empty_analytics()
        
        # Basic stats
        total_entries = len(moods)
        unique_users = len(set(mood['user_id'] for mood in moods))
        
        # Mood distribution
        mood_counts = Counter(mood['mood'] for mood in moods)
        mood_distribution = {
            'happy': mood_counts.get('happy', 0),
            'energetic': mood_counts.get('energetic', 0),
            'neutral': mood_counts.get('neutral', 0),
            'sad': mood_counts.get('sad', 0),
            'anxious': mood_counts.get('anxious', 0)
        }
        
        # Calculate percentages
        mood_percentages = {}
        for mood, count in mood_distribution.items():
            mood_percentages[mood] = round((count / total_entries * 100), 1) if total_entries > 0 else 0
        
        # Daily mood trends
        daily_trends = get_daily_mood_trends(moods, start_date, end_date)
        
        # Weekly patterns
        weekly_patterns = get_weekly_mood_patterns(moods)
        
        # Intensity analysis
        intensity_data = get_intensity_analysis(moods)
        
        # Trigger analysis
        trigger_data = get_trigger_analysis(moods)
        
        # User engagement
        user_engagement = get_user_engagement_data(moods)
        
        # Risk indicators
        risk_indicators = get_risk_indicators(moods)
        
        return {
            'total_entries': total_entries,
            'unique_users': unique_users,
            'mood_distribution': mood_distribution,
            'mood_percentages': mood_percentages,
            'daily_trends': daily_trends,
            'weekly_patterns': weekly_patterns,
            'intensity_data': intensity_data,
            'trigger_data': trigger_data,
            'user_engagement': user_engagement,
            'risk_indicators': risk_indicators,
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            }
        }
        
    except Exception as e:
        logger.error(f"Error analyzing mood data: {e}")
        return get_empty_analytics()

def get_daily_mood_trends(moods, start_date, end_date):
    """Get daily mood trends for chart visualization."""
    try:
        # Initialize daily data
        daily_data = defaultdict(lambda: {'happy': 0, 'energetic': 0, 'neutral': 0, 'sad': 0, 'anxious': 0, 'total': 0})
        
        # Group moods by date
        for mood in moods:
            date_str = mood['timestamp'].strftime('%Y-%m-%d')
            daily_data[date_str][mood['mood']] += 1
            daily_data[date_str]['total'] += 1
        
        # Create chart data
        chart_data = {
            'labels': [],
            'positive_trend': [],  # happy + energetic
            'neutral_trend': [],
            'negative_trend': []   # sad + anxious
        }
        
        # Fill in data for each day in range
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            label = current_date.strftime('%m/%d')
            
            data = daily_data[date_str]
            total = data['total']
            
            if total > 0:
                positive = ((data['happy'] + data['energetic']) / total) * 100
                neutral = (data['neutral'] / total) * 100
                negative = ((data['sad'] + data['anxious']) / total) * 100
            else:
                positive = neutral = negative = 0
            
            chart_data['labels'].append(label)
            chart_data['positive_trend'].append(round(positive, 1))
            chart_data['neutral_trend'].append(round(neutral, 1))
            chart_data['negative_trend'].append(round(negative, 1))
            
            current_date += timedelta(days=1)
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error getting daily trends: {e}")
        return {'labels': [], 'positive_trend': [], 'neutral_trend': [], 'negative_trend': []}

def get_weekly_mood_patterns(moods):
    """Analyze mood patterns by day of week."""
    try:
        # Initialize weekly data
        weekly_data = defaultdict(lambda: {'happy': 0, 'energetic': 0, 'neutral': 0, 'sad': 0, 'anxious': 0, 'total': 0})
        
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        # Group by day of week
        for mood in moods:
            day_name = mood['timestamp'].strftime('%A')
            weekly_data[day_name][mood['mood']] += 1
            weekly_data[day_name]['total'] += 1
        
        # Calculate percentages for each day
        chart_data = {
            'labels': days,
            'happy': [],
            'energetic': [],
            'neutral': [],
            'sad': [],
            'anxious': []
        }
        
        for day in days:
            data = weekly_data[day]
            total = data['total']
            
            for mood in ['happy', 'energetic', 'neutral', 'sad', 'anxious']:
                percentage = round((data[mood] / total * 100), 1) if total > 0 else 0
                chart_data[mood].append(percentage)
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error getting weekly patterns: {e}")
        return {'labels': [], 'happy': [], 'energetic': [], 'neutral': [], 'sad': [], 'anxious': []}

def get_intensity_analysis(moods):
    """Analyze mood intensity patterns."""
    try:
        intensities = [mood.get('intensity', 5) for mood in moods if mood.get('intensity')]
        
        if not intensities:
            return {'average': 0, 'distribution': {}}
        
        average_intensity = round(sum(intensities) / len(intensities), 1)
        
        # Intensity distribution
        intensity_counts = Counter(intensities)
        distribution = {}
        for i in range(1, 11):
            distribution[str(i)] = intensity_counts.get(i, 0)
        
        return {
            'average': average_intensity,
            'distribution': distribution,
            'total_with_intensity': len(intensities)
        }
        
    except Exception as e:
        logger.error(f"Error analyzing intensity: {e}")
        return {'average': 0, 'distribution': {}}

def get_trigger_analysis(moods):
    """Analyze mood triggers."""
    try:
        all_triggers = []
        mood_by_trigger = defaultdict(list)
        
        for mood in moods:
            triggers = mood.get('triggers', [])
            if isinstance(triggers, str):
                triggers = [t.strip() for t in triggers.split(',') if t.strip()]
            
            for trigger in triggers:
                all_triggers.append(trigger)
                mood_by_trigger[trigger].append(mood['mood'])
        
        if not all_triggers:
            return {'top_triggers': [], 'trigger_mood_impact': {}}
        
        # Top triggers
        trigger_counts = Counter(all_triggers)
        top_triggers = [{'name': trigger, 'count': count} 
                       for trigger, count in trigger_counts.most_common(10)]
        
        # Trigger mood impact
        trigger_impact = {}
        for trigger, mood_list in mood_by_trigger.items():
            if len(mood_list) >= 3:  # Only include triggers with enough data
                positive_count = sum(1 for m in mood_list if m in ['happy', 'energetic'])
                impact_score = round((positive_count / len(mood_list)) * 100, 1)
                trigger_impact[trigger] = {
                    'positive_percentage': impact_score,
                    'total_occurrences': len(mood_list)
                }
        
        return {
            'top_triggers': top_triggers,
            'trigger_mood_impact': trigger_impact
        }
        
    except Exception as e:
        logger.error(f"Error analyzing triggers: {e}")
        return {'top_triggers': [], 'trigger_mood_impact': {}}

def get_user_engagement_data(moods):
    """Analyze user engagement patterns."""
    try:
        user_data = defaultdict(int)
        
        for mood in moods:
            user_data[mood['user_id']] += 1
        
        # Calculate engagement stats
        total_users = len(user_data)
        entries_per_user = list(user_data.values())
        
        avg_entries = round(sum(entries_per_user) / len(entries_per_user), 1) if entries_per_user else 0
        
        # Categorize users by engagement
        high_engagement = sum(1 for count in entries_per_user if count >= 20)
        medium_engagement = sum(1 for count in entries_per_user if 10 <= count < 20)
        low_engagement = sum(1 for count in entries_per_user if count < 10)
        
        return {
            'total_active_users': total_users,
            'avg_entries_per_user': avg_entries,
            'engagement_distribution': {
                'high': high_engagement,
                'medium': medium_engagement,
                'low': low_engagement
            }
        }
        
    except Exception as e:
        logger.error(f"Error analyzing user engagement: {e}")
        return {'total_active_users': 0, 'avg_entries_per_user': 0, 'engagement_distribution': {}}

def get_risk_indicators(moods):
    """Identify potential mental health risk indicators."""
    try:
        # Recent negative mood patterns
        recent_moods = [m for m in moods if m['timestamp'] >= datetime.now(timezone.utc) - timedelta(days=7)]
        
        high_risk_users = set()
        concerning_patterns = []
        
        # Analyze by user
        user_moods = defaultdict(list)
        for mood in recent_moods:
            user_moods[mood['user_id']].append(mood)
        
        for user_id, user_mood_list in user_moods.items():
            if len(user_mood_list) >= 3:  # Need enough data
                negative_count = sum(1 for m in user_mood_list if m['mood'] in ['sad', 'anxious'])
                negative_ratio = negative_count / len(user_mood_list)
                
                if negative_ratio >= 0.7:  # 70% negative moods
                    high_risk_users.add(user_id)
                    concerning_patterns.append({
                        'user_id': user_id,
                        'negative_percentage': round(negative_ratio * 100, 1),
                        'total_entries': len(user_mood_list),
                        'pattern': 'High negative mood frequency'
                    })
        
        # Overall risk metrics
        total_negative = sum(1 for m in recent_moods if m['mood'] in ['sad', 'anxious'])
        risk_percentage = round((total_negative / len(recent_moods) * 100), 1) if recent_moods else 0
        
        return {
            'high_risk_user_count': len(high_risk_users),
            'concerning_patterns': concerning_patterns[:5],  # Top 5 concerning patterns
            'overall_risk_percentage': risk_percentage,
            'total_recent_entries': len(recent_moods)
        }
        
    except Exception as e:
        logger.error(f"Error analyzing risk indicators: {e}")
        return {'high_risk_user_count': 0, 'concerning_patterns': [], 'overall_risk_percentage': 0}

def get_empty_analytics():
    """Return empty analytics structure."""
    return {
        'total_entries': 0,
        'unique_users': 0,
        'mood_distribution': {'happy': 0, 'energetic': 0, 'neutral': 0, 'sad': 0, 'anxious': 0},
        'mood_percentages': {'happy': 0, 'energetic': 0, 'neutral': 0, 'sad': 0, 'anxious': 0},
        'daily_trends': {'labels': [], 'positive_trend': [], 'neutral_trend': [], 'negative_trend': []},
        'weekly_patterns': {'labels': [], 'happy': [], 'energetic': [], 'neutral': [], 'sad': [], 'anxious': []},
        'intensity_data': {'average': 0, 'distribution': {}},
        'trigger_data': {'top_triggers': [], 'trigger_mood_impact': {}},
        'user_engagement': {'total_active_users': 0, 'avg_entries_per_user': 0, 'engagement_distribution': {}},
        'risk_indicators': {'high_risk_user_count': 0, 'concerning_patterns': [], 'overall_risk_percentage': 0}
    }

# ===================================
# ADMIN MOOD REPORTS ROUTES
# ===================================

@admin_bp.route('/mood_reports')
@admin_required
def mood_reports():
    """Main mood reports dashboard."""
    try:
        # Get default analytics (30 days)
        analytics = get_mood_analytics_data('30_days')
        
        # Get user list for filtering
        users = list(mongo.db.users.find({}, {'_id': 1, 'email': 1, 'name': 1}).sort('name', 1))
        
        return render_template(
            'admin/mood_reports.html',
            analytics=analytics,
            users=users,
            selected_range='30_days',
            selected_user=None
        )
        
    except Exception as e:
        logger.error(f"Error in mood reports route: {e}")
        flash('Error loading mood reports. Please try again.', 'error')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/api/mood_analytics')
@admin_required
def api_mood_analytics():
    """API endpoint for mood analytics data."""
    try:
        date_range = request.args.get('range', '30_days')
        user_filter = request.args.get('user_id')
        
        analytics = get_mood_analytics_data(date_range, user_filter)
        
        return jsonify({
            'success': True,
            'data': analytics
        })
        
    except Exception as e:
        logger.error(f"Error in mood analytics API: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@admin_bp.route('/export_mood_report')
@admin_required
def export_mood_report():
    """Export mood report as CSV."""
    try:
        date_range = request.args.get('range', '30_days')
        user_filter = request.args.get('user_id')
        
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        if date_range == '7_days':
            start_date = end_date - timedelta(days=7)
        elif date_range == '30_days':
            start_date = end_date - timedelta(days=30)
        elif date_range == '90_days':
            start_date = end_date - timedelta(days=90)
        elif date_range == '1_year':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)
        
        # Build query
        query = {
            "timestamp": {"$gte": start_date, "$lte": end_date}
        }
        
        if user_filter:
            query["user_id"] = user_filter
        
        # Get mood data
        moods = list(mongo.db.moods.find(query).sort("timestamp", 1))
        
        # Create CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Date', 'User ID', 'Mood', 'Intensity', 'Triggers', 'Context'])
        
        # Write data
        for mood in moods:
            triggers = mood.get('triggers', [])
            if isinstance(triggers, list):
                triggers_str = ', '.join(triggers)
            else:
                triggers_str = str(triggers) if triggers else ''
            
            writer.writerow([
                mood['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                mood['user_id'],
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
                'Content-Disposition': f'attachment; filename=mood_report_{date_range}_{datetime.now().strftime("%Y%m%d")}.csv'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting mood report: {e}")
        flash('Error exporting report. Please try again.', 'error')
        return redirect(url_for('admin.mood_reports'))