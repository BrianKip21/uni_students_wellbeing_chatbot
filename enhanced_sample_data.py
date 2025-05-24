# enhanced_sample_data.py - Juicy sample data with real schedules

from wellbeing import create_app, mongo
from datetime import datetime

app = create_app()

def add_enhanced_therapists():
    """Add therapists with real availability schedules"""
    
    with app.app_context():
        print("🌟 Adding enhanced therapists with real schedules...")
        
        # Clear existing therapists
        mongo.db.therapists.delete_many({})
        
        enhanced_therapists = [
            {
                "name": "Dr. Sarah Johnson",
                "email": "sarah.johnson@university.edu",
                "license_number": "LIC12345",
                "specializations": ["anxiety", "depression", "cognitive_behavioral"],
                "bio": "Specializing in anxiety and depression with 8+ years of experience. I use evidence-based CBT techniques to help students develop practical coping skills and build resilience.",
                
                # REAL AVAILABILITY SCHEDULE
                "availability": {
                    "monday": ["09:00-12:00", "14:00-17:00"],
                    "tuesday": ["10:00-16:00"],
                    "wednesday": ["09:00-12:00", "13:00-18:00"],
                    "thursday": ["08:00-15:00"],
                    "friday": ["09:00-14:00"]
                },
                
                "max_students": 25,
                "current_students": 8,
                "rating": 4.9,
                "total_sessions": 203,
                "status": "active",
                "gender": "female",
                "phone": "+1-555-0101",
                "emergency_hours": True,
                "speciality_focus": "High-functioning anxiety and academic stress",
                "created_at": datetime.now()
            },
            
            {
                "name": "Dr. Michael Chen",
                "email": "michael.chen@university.edu", 
                "license_number": "LIC67890",
                "specializations": ["academic_stress", "anxiety", "stress_management"],
                "bio": "Academic stress specialist helping students navigate university pressures. I focus on mindfulness-based stress reduction and practical time management strategies.",
                
                "availability": {
                    "monday": ["11:00-18:00"],
                    "wednesday": ["09:00-17:00"],
                    "thursday": ["10:00-16:00"],
                    "friday": ["08:00-15:00"],
                    "saturday": ["10:00-14:00"]  # Weekend availability!
                },
                
                "max_students": 20,
                "current_students": 5,
                "rating": 4.7,
                "total_sessions": 156,
                "status": "active",
                "gender": "male",
                "phone": "+1-555-0102",
                "emergency_hours": False,
                "speciality_focus": "Study habits and test anxiety",
                "created_at": datetime.now()
            },
            
            {
                "name": "Dr. Emily Rodriguez",
                "email": "emily.rodriguez@university.edu",
                "license_number": "LIC11111",
                "specializations": ["trauma_therapy", "ptsd", "grief_counseling"],
                "bio": "Trauma-informed therapy specialist with expertise in PTSD and grief counseling. I provide a safe, supportive environment for healing from difficult experiences using EMDR and other evidence-based approaches.",
                
                "availability": {
                    "tuesday": ["09:00-18:00"],
                    "thursday": ["08:00-17:00"],
                    "friday": ["10:00-19:00"],
                    "saturday": ["09:00-15:00"]
                },
                
                "max_students": 15,
                "current_students": 12,
                "rating": 4.8,
                "total_sessions": 298,
                "status": "active",
                "gender": "female",
                "phone": "+1-555-0103",
                "emergency_hours": True,
                "speciality_focus": "Complex trauma and PTSD recovery",
                "created_at": datetime.now()
            },
            
            {
                "name": "Dr. James Wilson",
                "email": "james.wilson@university.edu",
                "license_number": "LIC22222",
                "specializations": ["substance_abuse", "addiction_counseling", "group_therapy"],
                "bio": "Addiction counselor with 12+ years helping students overcome substance use challenges. I offer both individual and group therapy with a non-judgmental, recovery-focused approach.",
                
                "availability": {
                    "monday": ["13:00-19:00"],
                    "tuesday": ["12:00-18:00"],
                    "wednesday": ["14:00-20:00"],
                    "thursday": ["13:00-17:00"],
                    "sunday": ["15:00-19:00"]  # Sunday evening sessions
                },
                
                "max_students": 22,
                "current_students": 7,
                "rating": 4.6,
                "total_sessions": 187,
                "status": "active",
                "gender": "male",
                "phone": "+1-555-0104",
                "emergency_hours": True,
                "speciality_focus": "Substance abuse and behavioral addictions",
                "created_at": datetime.now()
            },
            
            {
                "name": "Dr. Lisa Park",
                "email": "lisa.park@university.edu",
                "license_number": "LIC33333",
                "specializations": ["eating_disorders", "body_image", "self_esteem"],
                "bio": "Eating disorder specialist focusing on building healthy relationships with food and body image. I use a holistic approach addressing both mental and physical wellbeing with compassionate care.",
                
                "availability": {
                    "monday": ["08:00-16:00"],
                    "tuesday": ["09:00-17:00"],
                    "wednesday": ["07:00-15:00"],  # Early morning slots
                    "friday": ["09:00-18:00"]
                },
                
                "max_students": 18,
                "current_students": 11,
                "rating": 4.9,
                "total_sessions": 234,
                "status": "active",
                "gender": "female",
                "phone": "+1-555-0105",
                "emergency_hours": True,
                "speciality_focus": "Eating disorders and body dysmorphia",
                "created_at": datetime.now()
            },
            
            {
                "name": "Dr. David Kumar",
                "email": "david.kumar@university.edu",
                "license_number": "LIC44444",
                "specializations": ["relationship_counseling", "interpersonal", "family_therapy"],
                "bio": "Relationship and family therapist helping students navigate interpersonal challenges. I focus on communication skills, boundary setting, and building healthy relationships in all areas of life.",
                
                "availability": {
                    "tuesday": ["11:00-19:00"],
                    "wednesday": ["10:00-18:00"],
                    "thursday": ["12:00-20:00"],
                    "saturday": ["09:00-17:00"],
                    "sunday": ["12:00-18:00"]
                },
                
                "max_students": 20,
                "current_students": 9,
                "rating": 4.5,
                "total_sessions": 145,
                "status": "active",
                "gender": "male",
                "phone": "+1-555-0106",
                "emergency_hours": False,
                "speciality_focus": "Relationship dynamics and communication",
                "created_at": datetime.now()
            },
            
            # CRISIS SPECIALIST - Always available for high-priority cases
            {
                "name": "Dr. Amanda Torres",
                "email": "amanda.torres@university.edu",
                "license_number": "LIC55555",
                "specializations": ["crisis_intervention", "suicide_prevention", "emergency_therapy"],
                "bio": "Crisis intervention specialist available for urgent mental health situations. Trained in suicide prevention, crisis de-escalation, and emergency psychological support with immediate response capabilities.",
                
                "availability": {
                    "monday": ["08:00-20:00"],
                    "tuesday": ["08:00-20:00"],
                    "wednesday": ["08:00-20:00"],
                    "thursday": ["08:00-20:00"],
                    "friday": ["08:00-20:00"],
                    "saturday": ["10:00-18:00"],
                    "sunday": ["12:00-18:00"]
                },
                
                "max_students": 30,
                "current_students": 15,
                "rating": 5.0,
                "total_sessions": 412,
                "status": "active",
                "gender": "female",
                "phone": "+1-555-CRISIS",
                "emergency_hours": True,
                "crisis_specialist": True,
                "speciality_focus": "Emergency intervention and crisis stabilization",
                "created_at": datetime.now()
            }
        ]
        
        try:
            result = mongo.db.therapists.insert_many(enhanced_therapists)
            print(f"✅ Successfully inserted {len(result.inserted_ids)} enhanced therapists!")
            
            # Display therapists with their schedules
            print("\n📋 Enhanced Therapists Added:")
            for therapist in enhanced_therapists:
                name = therapist['name']
                specs = ', '.join(therapist['specializations'][:2])
                available_days = len(therapist['availability'])
                print(f"   • {name}")
                print(f"     - Specializes in: {specs}")
                print(f"     - Available {available_days} days/week")
                if therapist.get('crisis_specialist'):
                    print(f"     - 🚨 CRISIS SPECIALIST")
                if therapist.get('emergency_hours'):
                    print(f"     - 📞 Emergency hours available")
                print()
            
            return True
            
        except Exception as e:
            print(f"❌ Error inserting therapists: {e}")
            return False

def create_sample_appointments():
    """Create some sample appointments to show the system working"""
    
    with app.app_context():
        print("\n📅 Creating sample appointments...")
        
        # Get a therapist ID for demo
        therapist = mongo.db.therapists.find_one({'name': 'Dr. Sarah Johnson'})
        if not therapist:
            print("❌ No therapist found for sample appointments")
            return
        
        # Create sample booked slots to show realistic availability
        from datetime import timedelta
        sample_appointments = [
            {
                'therapist_id': therapist['_id'],
                'student_name': 'Demo Student 1',
                'datetime': datetime.now() + timedelta(days=1, hours=10),
                'status': 'confirmed',
                'type': 'virtual',
                'created_at': datetime.now()
            },
            {
                'therapist_id': therapist['_id'],
                'student_name': 'Demo Student 2', 
                'datetime': datetime.now() + timedelta(days=2, hours=14),
                'status': 'confirmed',
                'type': 'in_person',
                'created_at': datetime.now()
            }
        ]
        
        mongo.db.appointments.insert_many(sample_appointments)
        print(f"✅ Created {len(sample_appointments)} sample appointments")

def verify_enhanced_data():
    """Verify all the enhanced data is working"""
    
    with app.app_context():
        print("\n🔍 Verifying enhanced therapist data...")
        
        # Check therapists with availability
        therapists_with_schedule = mongo.db.therapists.count_documents({
            'availability': {'$exists': True, '$ne': {}}
        })
        print(f"✅ {therapists_with_schedule} therapists have availability schedules")
        
        # Check crisis specialist
        crisis_specialist = mongo.db.therapists.find_one({'crisis_specialist': True})
        if crisis_specialist:
            print(f"✅ Crisis specialist available: {crisis_specialist['name']}")
        
        # Check emergency hours
        emergency_therapists = mongo.db.therapists.count_documents({'emergency_hours': True})
        print(f"✅ {emergency_therapists} therapists offer emergency hours")
        
        # Check specializations variety
        all_specs = mongo.db.therapists.distinct('specializations')
        print(f"✅ {len(all_specs)} different specializations available")
        
        print("\n🎉 Enhanced sample data verification complete!")

def main():
    """Run all enhanced data setup"""
    print("🚀 Setting up ENHANCED sample data for juicy scheduling...")
    print("=" * 60)
    
    success_count = 0
    total_operations = 3
    
    # Add enhanced therapists
    if add_enhanced_therapists():
        success_count += 1
    
    # Create sample appointments
    try:
        create_sample_appointments()
        success_count += 1
    except Exception as e:
        print(f"❌ Sample appointments failed: {e}")
    
    # Verify data
    try:
        verify_enhanced_data()
        success_count += 1
    except Exception as e:
        print(f"❌ Verification failed: {e}")
    
    print("\n" + "=" * 60)
    print(f"🎯 Enhanced Setup Results: {success_count}/{total_operations} operations successful")
    
    if success_count == total_operations:
        print("🎉 ENHANCED SAMPLE DATA SETUP COMPLETED!")
        print("\nYour system now has:")
        print("   🏥 7 therapists with realistic availability schedules")
        print("   🚨 1 dedicated crisis intervention specialist")
        print("   📅 Real-time appointment slot filtering")
        print("   💻 Google Meet integration ready")
        print("   ⏰ Automatic scheduling with countdown timers")
        print("   📞 Emergency contact capabilities")
        print("\nNext steps:")
        print("   1. Run: python app.py")
        print("   2. Complete intake assessment")
        print("   3. Watch the magic happen! ✨")
    else:
        print("⚠️  Some setup failed. Check errors above.")
    
    return success_count == total_operations

if __name__ == "__main__":
    main()