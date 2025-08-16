"""
Admin API routes for Claude budget and spending reports.
File: wellbeing/blueprints/admin/api_budget.py
"""
import datetime
import csv
from io import StringIO
from flask import jsonify, request, current_app, make_response
from bson import ObjectId
from wellbeing.utils.decorators import login_required, admin_required
from wellbeing import logger

# Import mongo the same way your working admin routes do
from wellbeing import mongo

# Import the admin blueprint from the package
from . import admin_bp


@admin_bp.route('/api/budget/debug')
@login_required
@admin_required
def debug_budget_api():
    """Debug endpoint to check MongoDB connection and data."""
    try:
        debug_info = {
            'mongo_available': mongo is not None,
            'mongo_db_available': hasattr(mongo, 'db') if mongo else False,
            'current_app_available': current_app is not None
        }
        
        if mongo and hasattr(mongo, 'db'):
            try:
                # Test basic database access
                chat_count = mongo.db.chats.count_documents({})
                debug_info['chat_count'] = chat_count
                
                # Test if we can find any chats
                sample_chat = mongo.db.chats.find_one()
                debug_info['sample_chat_exists'] = sample_chat is not None
                
                if sample_chat:
                    debug_info['sample_chat_fields'] = list(sample_chat.keys())
                    debug_info['has_estimated_cost'] = 'estimated_cost' in sample_chat
                    debug_info['has_tokens_used'] = 'tokens_used' in sample_chat
                
            except Exception as db_error:
                debug_info['database_error'] = str(db_error)
        
        return jsonify({
            'status': 'success',
            'debug_info': debug_info
        })
        
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@admin_bp.route('/api/budget/summary')
@login_required
@admin_required
def budget_summary():
    """Get comprehensive budget summary for admin dashboard."""
    try:
        # Get current budget configuration
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        alert_threshold = current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
        
        # Get system-wide spending data
        monthly_summary = get_system_spending_summary(days=30)
        daily_summary = get_system_spending_summary(days=1)
        weekly_summary = get_system_spending_summary(days=7)
        
        # Calculate projections
        daily_avg = monthly_summary['total_cost'] / 30 if monthly_summary['total_messages'] > 0 else 0
        monthly_projection = daily_avg * 30
        
        summary = {
            'current_spending': {
                'today': round(daily_summary['total_cost'], 4),
                'this_week': round(weekly_summary['total_cost'], 4),
                'this_month': round(monthly_summary['total_cost'], 4),
                'monthly_projection': round(monthly_projection, 4)
            },
            'budget_limits': {
                'daily_limit': daily_budget,
                'monthly_limit': monthly_budget,
                'alert_threshold': alert_threshold
            },
            'usage_metrics': {
                'total_users': monthly_summary.get('unique_users', 0),
                'total_messages': monthly_summary.get('total_messages', 0),
                'total_tokens': monthly_summary.get('total_tokens', 0),
                'avg_cost_per_message': round(monthly_summary['total_cost'] / monthly_summary['total_messages'], 6) if monthly_summary['total_messages'] > 0 else 0,
                'avg_tokens_per_message': round(monthly_summary['total_tokens'] / monthly_summary['total_messages'], 1) if monthly_summary['total_messages'] > 0 else 0
            },
            'budget_health': {
                'daily_status': get_budget_status(daily_summary['total_cost'], daily_budget),
                'monthly_status': get_budget_status(monthly_summary['total_cost'], monthly_budget, alert_threshold),
                'daily_percentage': round((daily_summary['total_cost'] / daily_budget) * 100, 1) if daily_budget > 0 else 0,
                'monthly_percentage': round((monthly_summary['total_cost'] / monthly_budget) * 100, 1) if monthly_budget > 0 else 0
            },
            'alerts': generate_budget_alerts(daily_summary, monthly_summary, daily_budget, monthly_budget, alert_threshold)
        }
        
        return jsonify({
            'status': 'success',
            'summary': summary,
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'report_generated_by': 'admin_budget_summary'
        })
        
    except Exception as e:
        logger.error(f"Error generating admin budget summary: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@admin_bp.route('/api/budget/users')
@login_required
@admin_required
def user_spending_report():
    """Get detailed spending report by user."""
    try:
        period_days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 50, type=int)
        sort_by = request.args.get('sort_by', 'total_cost')  # total_cost, message_count, avg_cost
        
        # Get user spending data
        user_spending = get_user_spending_report(period_days, limit, sort_by)
        
        # Calculate system totals
        system_total_cost = sum(user['total_cost'] for user in user_spending) if user_spending else 0
        system_total_messages = sum(user['message_count'] for user in user_spending) if user_spending else 0
        system_total_tokens = sum(user['total_tokens'] for user in user_spending) if user_spending else 0
        
        # Identify high-usage users
        avg_cost_per_user = system_total_cost / len(user_spending) if user_spending else 0
        high_usage_threshold = max(avg_cost_per_user * 2, 0.05)  # At least $0.05 threshold
        
        high_usage_users = [user for user in user_spending if user['total_cost'] > high_usage_threshold]
        
        report = {
            'period_days': period_days,
            'total_users': len(user_spending),
            'system_totals': {
                'total_cost': round(system_total_cost, 4),
                'total_messages': system_total_messages,
                'total_tokens': system_total_tokens,
                'avg_cost_per_user': round(avg_cost_per_user, 4),
                'avg_messages_per_user': round(system_total_messages / len(user_spending), 1) if user_spending else 0
            },
            'user_breakdown': user_spending,
            'insights': {
                'top_spenders': user_spending[:10],  # Top 10 by current sort
                'high_usage_users': high_usage_users,
                'cost_distribution': calculate_cost_distribution(user_spending),
                'usage_patterns': analyze_usage_patterns(user_spending)
            },
            'budget_analysis': {
                'users_over_daily_limit': len([u for u in user_spending if u.get('daily_avg_cost', 0) > current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)]),
                'projected_monthly_cost': round((system_total_cost / period_days) * 30, 4) if period_days > 0 else 0,
                'cost_efficiency': round(system_total_messages / system_total_cost, 1) if system_total_cost > 0 else 0
            }
        }
        
        return jsonify({
            'status': 'success',
            'report': report,
            'generated_at': datetime.datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error generating user spending report: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@admin_bp.route('/api/budget/trends')
@login_required
@admin_required
def cost_trends():
    """Get cost trends and forecasting data."""
    try:
        days = request.args.get('days', 90, type=int)
        granularity = request.args.get('granularity', 'daily')  # daily, weekly, monthly
        
        # Get historical spending data
        trends_data = get_cost_trends(days, granularity)
        
        # Calculate trends and predictions
        if len(trends_data) >= 7:  # Need at least a week of data
            trend_analysis = analyze_spending_trends(trends_data)
            forecasting = generate_spending_forecast(trends_data, periods=30)
        else:
            trend_analysis = {'status': 'insufficient_data', 'message': 'Need at least 7 data points for trend analysis'}
            forecasting = {'status': 'insufficient_data', 'message': 'Need at least 7 data points for forecasting'}
        
        response = {
            'status': 'success',
            'period_days': days,
            'granularity': granularity,
            'data_points': len(trends_data),
            'trends': trends_data,
            'analysis': trend_analysis,
            'forecast': forecasting,
            'budget_projections': {
                'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                'projected_monthly_spend': forecasting.get('monthly_projection', 0),
                'budget_utilization_forecast': forecasting.get('budget_utilization', 0),
                'recommended_adjustments': generate_budget_recommendations(trend_analysis, forecasting)
            }
        }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error generating cost trends: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@admin_bp.route('/api/budget/detailed')
@login_required
@admin_required
def detailed_report():
    """Generate comprehensive budget report."""
    try:
        period_days = request.args.get('days', 30, type=int)
        include_users = request.args.get('include_users', True, type=bool)
        include_trends = request.args.get('include_trends', True, type=bool)
        
        report_data = {
            'metadata': {
                'period_days': period_days,
                'generated_at': datetime.datetime.utcnow().isoformat(),
                'generated_by': 'admin_detailed_report',
                'config': {
                    'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                    'daily_budget': current_app.config.get('DAILY_SPENDING_LIMIT', 0.50),
                    'alert_threshold': current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00),
                    'claude_model': current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307')
                }
            }
        }
        
        # System summary
        system_summary = get_system_spending_summary(period_days)
        report_data['system_summary'] = system_summary
        
        # User breakdown if requested
        if include_users:
            user_spending = get_user_spending_report(period_days, limit=100, sort_by='total_cost')
            report_data['user_analysis'] = {
                'user_breakdown': user_spending,
                'insights': {
                    'cost_distribution': calculate_cost_distribution(user_spending),
                    'usage_patterns': analyze_usage_patterns(user_spending)
                }
            }
        
        # Trends if requested
        if include_trends:
            trends_data = get_cost_trends(period_days, 'daily')
            if len(trends_data) >= 7:
                report_data['trends'] = {
                    'data': trends_data,
                    'analysis': analyze_spending_trends(trends_data),
                    'forecast': generate_spending_forecast(trends_data)
                }
        
        # Overall assessment
        report_data['assessment'] = generate_budget_assessment(report_data)
        
        return jsonify({
            'status': 'success',
            'report': report_data
        })
        
    except Exception as e:
        logger.error(f"Error generating detailed budget report: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@admin_bp.route('/api/budget/export')
@login_required
@admin_required
def export_report():
    """Export budget report in various formats."""
    try:
        period_days = request.args.get('days', 30, type=int)
        format_type = request.args.get('format', 'csv').lower()  # csv, json
        report_type = request.args.get('type', 'summary')  # summary, users, detailed
        
        if format_type not in ['csv', 'json']:
            return jsonify({
                'error': 'Unsupported export format',
                'supported_formats': ['csv', 'json']
            }), 400
        
        # Generate export data based on type
        if report_type == 'users':
            export_data = get_user_spending_report(period_days, limit=1000, sort_by='total_cost')
            filename = f'claude_user_spending_{datetime.date.today()}'
        elif report_type == 'detailed':
            export_data = generate_detailed_export_data(period_days)
            filename = f'claude_detailed_report_{datetime.date.today()}'
        else:  # summary
            export_data = get_system_spending_summary(period_days)
            filename = f'claude_budget_summary_{datetime.date.today()}'
        
        if format_type == 'json':
            response = make_response(jsonify(export_data))
            response.headers['Content-Disposition'] = f'attachment; filename={filename}.json'
            response.headers['Content-Type'] = 'application/json'
            return response
            
        elif format_type == 'csv':
            csv_content = convert_to_csv(export_data, report_type)
            response = make_response(csv_content)
            response.headers['Content-Disposition'] = f'attachment; filename={filename}.csv'
            response.headers['Content-Type'] = 'text/csv'
            return response
            
    except Exception as e:
        logger.error(f"Error exporting budget report: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@admin_bp.route('/api/budget/alerts')
@login_required
@admin_required
def budget_alerts():
    """Get current budget alerts and notifications."""
    try:
        # Get current spending
        daily_summary = get_system_spending_summary(days=1)
        monthly_summary = get_system_spending_summary(days=30)
        
        # Get budget limits
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        alert_threshold = current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
        
        # Generate alerts
        alerts = generate_budget_alerts(daily_summary, monthly_summary, daily_budget, monthly_budget, alert_threshold)
        
        # Add additional system health checks
        system_alerts = []
        
        # Check for unusual spending patterns
        weekly_summary = get_system_spending_summary(days=7)
        weekly_avg = weekly_summary['total_cost'] / 7
        if daily_summary['total_cost'] > weekly_avg * 3:
            system_alerts.append({
                'type': 'warning',
                'category': 'unusual_spending',
                'message': 'Today\'s spending is significantly higher than weekly average',
                'value': daily_summary['total_cost'],
                'comparison': weekly_avg
            })
        
        # Check for rapid token usage
        if daily_summary['total_tokens'] > 50000:  # Configurable threshold
            system_alerts.append({
                'type': 'info',
                'category': 'high_token_usage',
                'message': 'High token usage detected today',
                'value': daily_summary['total_tokens']
            })
        
        return jsonify({
            'status': 'success',
            'budget_alerts': alerts,
            'system_alerts': system_alerts,
            'alert_summary': {
                'total_alerts': len(alerts) + len(system_alerts),
                'critical_count': len([a for a in alerts + system_alerts if a['type'] == 'critical']),
                'warning_count': len([a for a in alerts + system_alerts if a['type'] == 'warning']),
                'info_count': len([a for a in alerts + system_alerts if a['type'] == 'info'])
            },
            'generated_at': datetime.datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error generating budget alerts: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


# Helper Functions
def get_system_spending_summary(days=30):
    """Get system-wide spending summary for the specified period."""
    try:
        end_date = datetime.datetime.utcnow()
        start_date = end_date - datetime.timedelta(days=days)
        
        # First, let's update your existing create_chat function to store cost data
        # Your chatbot service already calculates costs, we just need to store them
        
        pipeline = [
            {
                '$match': {
                    'timestamp': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': None,
                    'total_messages': {'$sum': 1},
                    'unique_users': {'$addToSet': '$user_id'},
                    'avg_confidence': {'$avg': {'$ifNull': ['$confidence', 0]}},
                    # Sum estimated_cost if it exists, otherwise calculate from tokens
                    'total_cost': {
                        '$sum': {
                            '$cond': {
                                'if': {'$ne': ['$estimated_cost', None]},
                                'then': '$estimated_cost',
                                'else': {
                                    '$multiply': [
                                        {'$ifNull': ['$tokens_used', 0]},
                                        0.000005  # Rough estimate: $0.000005 per token for Haiku
                                    ]
                                }
                            }
                        }
                    },
                    'total_tokens': {'$sum': {'$ifNull': ['$tokens_used', 0]}}
                }
            }
        ]
        
        result = list(mongo.db.chats.aggregate(pipeline))
        
        if result:
            data = result[0]
            total_messages = data.get('total_messages', 0)
            total_cost = data.get('total_cost', 0)
            total_tokens = data.get('total_tokens', 0)
            
            return {
                'total_cost': round(total_cost, 6),
                'total_messages': total_messages,
                'total_tokens': total_tokens,
                'unique_users': len(data.get('unique_users', [])),
                'avg_confidence': round(data.get('avg_confidence', 0), 2),
                'period_days': days,
                'avg_cost_per_message': round(total_cost / max(total_messages, 1), 6),
                'avg_cost_per_day': round(total_cost / days, 6)
            }
        else:
            return {
                'total_cost': 0,
                'total_messages': 0,
                'total_tokens': 0,
                'unique_users': 0,
                'avg_confidence': 0,
                'period_days': days,
                'avg_cost_per_message': 0,
                'avg_cost_per_day': 0
            }
            
    except Exception as e:
        logger.error(f"Error getting system spending summary: {e}")
        return {
            'total_cost': 0,
            'total_messages': 0,
            'total_tokens': 0,
            'unique_users': 0,
            'avg_confidence': 0,
            'period_days': days,
            'avg_cost_per_message': 0,
            'avg_cost_per_day': 0
        }


def get_user_spending_report(period_days, limit, sort_by):
    """Get detailed user spending report."""
    try:
        end_date = datetime.datetime.utcnow()
        start_date = end_date - datetime.timedelta(days=period_days)
        
        # First, let's get the raw data and debug the user_id types
        pipeline = [
            {
                '$match': {
                    'timestamp': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': '$user_id',
                    'message_count': {'$sum': 1},
                    'avg_confidence': {'$avg': {'$ifNull': ['$confidence', 0]}},
                    'last_activity': {'$max': '$timestamp'},
                    'first_activity': {'$min': '$timestamp'},
                    # Calculate total cost from estimated_cost or tokens
                    'total_cost': {
                        '$sum': {
                            '$cond': {
                                'if': {'$ne': ['$estimated_cost', None]},
                                'then': '$estimated_cost',
                                'else': {
                                    '$multiply': [
                                        {'$ifNull': ['$tokens_used', 0]},
                                        0.000005  # Rough estimate for Haiku
                                    ]
                                }
                            }
                        }
                    },
                    'total_tokens': {'$sum': {'$ifNull': ['$tokens_used', 0]}}
                }
            },
            {
                '$addFields': {
                    'avg_cost_per_message': {
                        '$cond': {
                            'if': {'$gt': ['$message_count', 0]},
                            'then': {'$divide': ['$total_cost', '$message_count']},
                            'else': 0
                        }
                    },
                    'daily_avg_cost': {
                        '$divide': ['$total_cost', period_days]
                    }
                }
            }
        ]
        
        # Add sorting
        sort_field_map = {
            'total_cost': {'total_cost': -1},
            'message_count': {'message_count': -1},
            'avg_cost': {'avg_cost_per_message': -1}
        }
        
        sort_criteria = sort_field_map.get(sort_by, {'total_cost': -1})
        pipeline.append({'$sort': sort_criteria})
        pipeline.append({'$limit': limit})
        
        results = list(mongo.db.chats.aggregate(pipeline))
        
        # Format results and manually lookup users
        formatted_results = []
        for result in results:
            user_id = result['_id']
            
            # Try different ways to find the user
            user_info = None
            
            # Method 1: Direct lookup if user_id is already ObjectId
            if isinstance(user_id, ObjectId):
                user_info = mongo.db.users.find_one({'_id': user_id})
            
            # Method 2: Convert string to ObjectId if needed
            elif isinstance(user_id, str):
                try:
                    if ObjectId.is_valid(user_id):
                        user_info = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                    else:
                        # Try finding by other fields if it's not a valid ObjectId
                        user_info = mongo.db.users.find_one({'$or': [
                            {'username': user_id},
                            {'email': user_id},
                            {'user_id': user_id}
                        ]})
                except:
                    pass
            
            # Extract username from user info
            username = "Unknown"
            email = "Unknown"
            
            if user_info:
                # Try different username field combinations
                if 'first_name' in user_info and 'last_name' in user_info:
                    first_name = user_info.get('first_name', '').strip()
                    last_name = user_info.get('last_name', '').strip()
                    if first_name or last_name:
                        username = f"{first_name} {last_name}".strip()
                elif 'username' in user_info and user_info['username']:
                    username = user_info['username']
                elif 'email' in user_info and user_info['email']:
                    username = user_info['email'].split('@')[0]  # Use email prefix as username
                
                # Get email
                if 'email' in user_info and user_info['email']:
                    email = user_info['email']
            
            # If still unknown, try to make a meaningful display from user_id
            if username == "Unknown":
                if isinstance(user_id, str) and '@' in user_id:
                    username = user_id.split('@')[0]
                    email = user_id
                elif isinstance(user_id, str):
                    username = f"User {user_id[:8]}..."  # Show first 8 chars of user_id
                else:
                    username = f"User {str(user_id)[:8]}..."
            
            formatted_results.append({
                'user_id': str(user_id) if user_id else 'Unknown',
                'username': username,
                'email': email,
                'total_cost': round(result.get('total_cost', 0), 6),
                'message_count': result.get('message_count', 0),
                'total_tokens': result.get('total_tokens', 0),
                'avg_cost_per_message': round(result.get('avg_cost_per_message', 0), 6),
                'avg_tokens_per_message': round(result.get('total_tokens', 0) / max(result.get('message_count', 1), 1), 1),
                'avg_confidence': round(result.get('avg_confidence', 0), 2),
                'last_activity': result['last_activity'].isoformat() if result.get('last_activity') else None,
                'first_activity': result['first_activity'].isoformat() if result.get('first_activity') else None,
                'daily_avg_cost': round(result.get('daily_avg_cost', 0), 6),
                'activity_days': (result['last_activity'] - result['first_activity']).days + 1 if result.get('last_activity') and result.get('first_activity') else 1,
                'debug_user_id_type': type(user_id).__name__,  # For debugging
                'debug_user_found': user_info is not None  # For debugging
            })
        
        return formatted_results
        
    except Exception as e:
        logger.error(f"Error getting user spending report: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return []


def get_cost_trends(days, granularity):
    """Get historical cost trends data."""
    try:
        end_date = datetime.datetime.utcnow()
        start_date = end_date - datetime.timedelta(days=days)
        
        # Create grouping based on granularity
        if granularity == 'daily':
            group_format = {
                'year': {'$year': '$timestamp'},
                'month': {'$month': '$timestamp'},
                'day': {'$dayOfMonth': '$timestamp'}
            }
        elif granularity == 'weekly':
            group_format = {
                'year': {'$year': '$timestamp'},
                'week': {'$week': '$timestamp'}
            }
        else:  # monthly
            group_format = {
                'year': {'$year': '$timestamp'},
                'month': {'$month': '$timestamp'}
            }
        
        pipeline = [
            {
                '$match': {
                    'timestamp': {'$gte': start_date, '$lte': end_date}
                }
            },
            {
                '$group': {
                    '_id': group_format,
                    'message_count': {'$sum': 1},
                    'unique_users': {'$addToSet': '$user_id'},
                    # Calculate total cost
                    'total_cost': {
                        '$sum': {
                            '$cond': {
                                'if': {'$ne': ['$estimated_cost', None]},
                                'then': '$estimated_cost',
                                'else': {
                                    '$multiply': [
                                        {'$ifNull': ['$tokens_used', 0]},
                                        0.000005  # Rough estimate for Haiku
                                    ]
                                }
                            }
                        }
                    },
                    'total_tokens': {'$sum': {'$ifNull': ['$tokens_used', 0]}}
                }
            },
            {
                '$addFields': {
                    'unique_user_count': {'$size': '$unique_users'},
                    'avg_cost_per_message': {
                        '$cond': {
                            'if': {'$gt': ['$message_count', 0]},
                            'then': {'$divide': ['$total_cost', '$message_count']},
                            'else': 0
                        }
                    }
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        results = list(mongo.db.chats.aggregate(pipeline))
        
        # Format results
        formatted_results = []
        for result in results:
            if granularity == 'daily':
                date_str = f"{result['_id']['year']}-{result['_id']['month']:02d}-{result['_id']['day']:02d}"
            elif granularity == 'weekly':
                date_str = f"{result['_id']['year']}-W{result['_id']['week']:02d}"
            else:
                date_str = f"{result['_id']['year']}-{result['_id']['month']:02d}"
            
            formatted_results.append({
                'date': date_str,
                'total_cost': round(result.get('total_cost', 0), 6),
                'message_count': result.get('message_count', 0),
                'total_tokens': result.get('total_tokens', 0),
                'unique_users': result.get('unique_user_count', 0),
                'avg_cost_per_message': round(result.get('avg_cost_per_message', 0), 6)
            })
        
        return formatted_results
        
    except Exception as e:
        logger.error(f"Error getting cost trends: {e}")
        return []


def calculate_cost_distribution(user_spending):
    """Calculate cost distribution statistics."""
    if not user_spending:
        return {}
    
    costs = [user['total_cost'] for user in user_spending]
    costs.sort()
    
    n = len(costs)
    return {
        'min': round(min(costs), 6),
        'max': round(max(costs), 6),
        'median': round(costs[n//2], 6),
        'q25': round(costs[n//4], 6) if n >= 4 else round(costs[0], 6),
        'q75': round(costs[3*n//4], 6) if n >= 4 else round(costs[-1], 6),
        'mean': round(sum(costs) / n, 6),
        'std_dev': round(calculate_std_dev(costs), 6),
        'cost_ranges': {
            'low_cost': len([c for c in costs if c <= 0.01]),
            'medium_cost': len([c for c in costs if 0.01 < c <= 0.10]),
            'high_cost': len([c for c in costs if c > 0.10])
        }
    }


def analyze_usage_patterns(user_spending):
    """Analyze user usage patterns."""
    if not user_spending:
        return {}
    
    total_users = len(user_spending)
    active_users = len([u for u in user_spending if u['message_count'] > 5])
    heavy_users = len([u for u in user_spending if u['message_count'] > 20])
    
    return {
        'user_segments': {
            'total_users': total_users,
            'active_users': active_users,
            'heavy_users': heavy_users,
            'light_users': total_users - active_users
        },
        'engagement_metrics': {
            'active_user_percentage': round((active_users / total_users) * 100, 1) if total_users > 0 else 0,
            'heavy_user_percentage': round((heavy_users / total_users) * 100, 1) if total_users > 0 else 0,
            'avg_messages_per_active_user': round(
                sum(u['message_count'] for u in user_spending if u['message_count'] > 5) / active_users, 1
            ) if active_users > 0 else 0
        },
        'cost_efficiency': {
            'cost_per_active_user': round(
                sum(u['total_cost'] for u in user_spending if u['message_count'] > 5) / active_users, 4
            ) if active_users > 0 else 0,
            'messages_per_dollar': round(
                sum(u['message_count'] for u in user_spending) / sum(u['total_cost'] for u in user_spending), 1
            ) if sum(u['total_cost'] for u in user_spending) > 0 else 0
        }
    }


def analyze_spending_trends(trends_data):
    """Analyze spending trends for patterns."""
    if len(trends_data) < 7:
        return {'status': 'insufficient_data'}
    
    costs = [point['total_cost'] for point in trends_data]
    messages = [point['message_count'] for point in trends_data]
    
    cost_trend = calculate_trend(costs)
    message_trend = calculate_trend(messages)
    
    return {
        'cost_trend': {
            'slope': round(cost_trend, 6),
            'direction': 'increasing' if cost_trend > 0.001 else 'decreasing' if cost_trend < -0.001 else 'stable',
            'weekly_change': round(cost_trend * 7, 6),
            'monthly_change': round(cost_trend * 30, 6)
        },
        'usage_trend': {
            'slope': round(message_trend, 2),
            'direction': 'increasing' if message_trend > 0.1 else 'decreasing' if message_trend < -0.1 else 'stable'
        },
        'recent_average': {
            'cost': round(sum(costs[-7:]) / min(7, len(costs)), 6),
            'messages': round(sum(messages[-7:]) / min(7, len(messages)), 1)
        },
        'volatility': {
            'cost_std_dev': round(calculate_std_dev(costs[-14:]), 6),
            'message_std_dev': round(calculate_std_dev(messages[-14:]), 2)
        }
    }


def generate_spending_forecast(trends_data, periods=30):
    """Generate spending forecasts."""
    if len(trends_data) < 7:
        return {'status': 'insufficient_data'}
    
    recent_costs = [point['total_cost'] for point in trends_data[-14:]]  # Last 14 periods
    recent_messages = [point['message_count'] for point in trends_data[-14:]]
    
    daily_average_cost = sum(recent_costs) / len(recent_costs)
    daily_average_messages = sum(recent_messages) / len(recent_messages)
    
    # Simple projection with trend adjustment
    cost_trend = calculate_trend([point['total_cost'] for point in trends_data])
    
    # Project future spending
    monthly_projection = (daily_average_cost + cost_trend * periods / 2) * periods
    weekly_projection = (daily_average_cost + cost_trend * 7 / 2) * 7
    
    monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
    budget_utilization = (monthly_projection / monthly_budget) * 100 if monthly_budget > 0 else 0
    
    return {
        'daily_projection': round(daily_average_cost + cost_trend, 6),
        'weekly_projection': round(weekly_projection, 6),
        'monthly_projection': round(monthly_projection, 6),
        'budget_utilization': round(budget_utilization, 1),
        'forecast_confidence': get_forecast_confidence(trends_data),
        'days_until_budget_exhausted': int(monthly_budget / daily_average_cost) if daily_average_cost > 0 else float('inf'),
        'projected_messages_per_day': round(daily_average_messages, 1)
    }


def generate_budget_recommendations(trend_analysis, forecasting):
    """Generate budget adjustment recommendations."""
    recommendations = []
    
    if forecasting.get('status') == 'insufficient_data':
        recommendations.append({
            'type': 'data_collection',
            'priority': 'low',
            'message': 'Collect more usage data for better forecasting',
            'action': 'Continue monitoring for at least 7 days'
        })
        return recommendations
    
    budget_utilization = forecasting.get('budget_utilization', 0)
    cost_direction = trend_analysis.get('cost_trend', {}).get('direction', 'stable')
    
    if budget_utilization > 100:
        recommendations.append({
            'type': 'budget_increase',
            'priority': 'high',
            'message': 'Consider increasing monthly budget to accommodate projected usage',
            'suggested_budget': round(forecasting.get('monthly_projection', 0) * 1.2, 2),
            'current_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        })
    
    if cost_direction == 'increasing':
        recommendations.append({
            'type': 'usage_optimization',
            'priority': 'medium',
            'message': 'Review high-usage users and implement usage guidelines',
            'details': 'Cost trend is increasing - consider user education or usage limits'
        })
    
    if budget_utilization > 80 and cost_direction != 'decreasing':
        recommendations.append({
            'type': 'monitoring',
            'priority': 'medium',
            'message': 'Increase monitoring frequency due to high budget utilization',
            'action': 'Set up daily budget alerts'
        })
    
    # Check for efficiency improvements
    avg_cost_per_message = forecasting.get('monthly_projection', 0) / forecasting.get('projected_messages_per_day', 1) / 30
    if avg_cost_per_message > 0.01:  # Threshold for expensive per-message cost
        recommendations.append({
            'type': 'efficiency',
            'priority': 'low',
            'message': 'Consider optimizing prompts or using a less expensive model for simple queries',
            'current_cost_per_message': round(avg_cost_per_message, 6)
        })
    
    return recommendations


def generate_budget_alerts(daily_summary, monthly_summary, daily_budget, monthly_budget, alert_threshold):
    """Generate budget alerts based on current spending."""
    alerts = []
    
    # Daily alerts
    daily_percentage = (daily_summary['total_cost'] / daily_budget) * 100 if daily_budget > 0 else 0
    if daily_percentage >= 100:
        alerts.append({
            'type': 'critical',
            'category': 'daily_budget',
            'message': f'Daily budget exceeded ({daily_percentage:.1f}%)',
            'value': daily_summary['total_cost'],
            'limit': daily_budget,
            'percentage': daily_percentage
        })
    elif daily_percentage >= 90:
        alerts.append({
            'type': 'critical',
            'category': 'daily_budget',
            'message': f'Daily spending at {daily_percentage:.1f}% of budget',
            'value': daily_summary['total_cost'],
            'limit': daily_budget,
            'percentage': daily_percentage
        })
    elif daily_percentage >= 75:
        alerts.append({
            'type': 'warning',
            'category': 'daily_budget',
            'message': f'Daily spending at {daily_percentage:.1f}% of budget',
            'value': daily_summary['total_cost'],
            'limit': daily_budget,
            'percentage': daily_percentage
        })
    
    # Monthly alerts
    monthly_percentage = (monthly_summary['total_cost'] / monthly_budget) * 100 if monthly_budget > 0 else 0
    if monthly_summary['total_cost'] >= monthly_budget:
        alerts.append({
            'type': 'critical',
            'category': 'monthly_budget',
            'message': f'Monthly budget exceeded ({monthly_percentage:.1f}%)',
            'value': monthly_summary['total_cost'],
            'limit': monthly_budget,
            'percentage': monthly_percentage
        })
    elif monthly_summary['total_cost'] >= alert_threshold:
        alerts.append({
            'type': 'warning',
            'category': 'monthly_budget',
            'message': f'Monthly spending at {monthly_percentage:.1f}% of budget',
            'value': monthly_summary['total_cost'],
            'limit': monthly_budget,
            'percentage': monthly_percentage
        })
    
    # Usage pattern alerts
    if daily_summary['total_messages'] > 500:  # Configurable threshold
        alerts.append({
            'type': 'info',
            'category': 'high_usage',
            'message': f'High message volume today ({daily_summary["total_messages"]} messages)',
            'value': daily_summary['total_messages']
        })
    
    return alerts


def get_budget_status(current_spend, budget_limit, alert_threshold=None):
    """Get budget status based on current spending."""
    if alert_threshold is None:
        alert_threshold = budget_limit * 0.8
    
    if current_spend >= budget_limit:
        return 'critical'
    elif current_spend >= alert_threshold:
        return 'warning'
    elif current_spend >= budget_limit * 0.5:
        return 'moderate'
    else:
        return 'ok'


def calculate_std_dev(numbers):
    """Calculate standard deviation."""
    if len(numbers) < 2:
        return 0
    mean = sum(numbers) / len(numbers)
    variance = sum((x - mean) ** 2 for x in numbers) / (len(numbers) - 1)
    return variance ** 0.5


def calculate_trend(values):
    """Calculate linear trend slope."""
    n = len(values)
    if n < 2:
        return 0
    x_sum = sum(range(n))
    y_sum = sum(values)
    xy_sum = sum(i * values[i] for i in range(n))
    x_squared_sum = sum(i * i for i in range(n))
    
    denominator = n * x_squared_sum - x_sum * x_sum
    if denominator == 0:
        return 0
    
    slope = (n * xy_sum - x_sum * y_sum) / denominator
    return slope


def get_forecast_confidence(trends_data):
    """Calculate forecast confidence based on data quality."""
    if len(trends_data) < 7:
        return 'low'
    elif len(trends_data) < 14:
        return 'medium'
    
    # Check data consistency
    costs = [point['total_cost'] for point in trends_data]
    std_dev = calculate_std_dev(costs)
    mean_cost = sum(costs) / len(costs)
    
    coefficient_of_variation = std_dev / mean_cost if mean_cost > 0 else 1
    
    if coefficient_of_variation < 0.3:
        return 'high'
    elif coefficient_of_variation < 0.6:
        return 'medium'
    else:
        return 'low'


def generate_budget_assessment(report_data):
    """Generate overall budget assessment."""
    system_summary = report_data.get('system_summary', {})
    monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
    
    current_spend = system_summary.get('total_cost', 0)
    budget_percentage = (current_spend / monthly_budget) * 100 if monthly_budget > 0 else 0
    
    assessment = {
        'overall_status': get_budget_status(current_spend, monthly_budget),
        'budget_utilization': round(budget_percentage, 1),
        'spending_efficiency': {
            'cost_per_message': system_summary.get('avg_cost_per_message', 0),
            'messages_per_user': round(
                system_summary.get('total_messages', 0) / max(system_summary.get('unique_users', 1), 1), 1
            ),
            'cost_per_user': round(
                current_spend / max(system_summary.get('unique_users', 1), 1), 4
            )
        },
        'risk_factors': [],
        'opportunities': []
    }
    
    # Identify risk factors
    if budget_percentage > 90:
        assessment['risk_factors'].append('Budget nearly exhausted')
    if system_summary.get('avg_cost_per_message', 0) > 0.01:
        assessment['risk_factors'].append('High cost per message')
    
    # Identify opportunities
    if budget_percentage < 50:
        assessment['opportunities'].append('Budget underutilized - consider expanding access')
    if system_summary.get('unique_users', 0) < 10:
        assessment['opportunities'].append('Low user adoption - consider user engagement initiatives')
    
    return assessment


def generate_detailed_export_data(period_days):
    """Generate comprehensive data for detailed export."""
    return {
        'metadata': {
            'period_days': period_days,
            'generated_at': datetime.datetime.utcnow().isoformat(),
            'export_type': 'detailed'
        },
        'system_summary': get_system_spending_summary(period_days),
        'user_breakdown': get_user_spending_report(period_days, limit=1000, sort_by='total_cost'),
        'daily_trends': get_cost_trends(period_days, 'daily'),
        'config': {
            'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
            'daily_budget': current_app.config.get('DAILY_SPENDING_LIMIT', 0.50),
            'alert_threshold': current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00),
            'claude_model': current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307')
        }
    }


def convert_to_csv(export_data, report_type):
    """Convert report data to CSV format."""
    output = StringIO()
    
    if report_type == 'users':
        fieldnames = ['user_id', 'username', 'email', 'total_cost', 'message_count', 
                     'total_tokens', 'avg_cost_per_message', 'avg_tokens_per_message',
                     'avg_confidence', 'last_activity', 'daily_avg_cost']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for user in export_data:
            writer.writerow(user)
    
    elif report_type == 'summary':
        writer = csv.writer(output)
        writer.writerow(['Metric', 'Value'])
        
        for key, value in export_data.items():
            if isinstance(value, (int, float, str)):
                writer.writerow([key.replace('_', ' ').title(), value])
    
    elif report_type == 'detailed':
        # Create multiple sections in CSV
        writer = csv.writer(output)
        
        # System summary section
        writer.writerow(['=== SYSTEM SUMMARY ==='])
        writer.writerow(['Metric', 'Value'])
        system_summary = export_data.get('system_summary', {})
        for key, value in system_summary.items():
            writer.writerow([key.replace('_', ' ').title(), value])
        
        writer.writerow([])  # Empty row
        
        # User breakdown section
        writer.writerow(['=== TOP USERS BY SPENDING ==='])
        user_fieldnames = ['User ID', 'Username', 'Total Cost', 'Message Count', 'Avg Cost/Message']
        writer.writerow(user_fieldnames)
        
        for user in export_data.get('user_breakdown', [])[:20]:  # Top 20 users
            writer.writerow([
                user['user_id'],
                user['username'],
                user['total_cost'],
                user['message_count'],
                user['avg_cost_per_message']
            ])
    
    return output.getvalue()