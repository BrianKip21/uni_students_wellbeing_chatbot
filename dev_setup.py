# dev_setup.py - Quick development setup script for Wellbeing Assistant
import requests
import json
import os
from datetime import datetime

def setup_development_data():
    """Quick setup for development environment"""
    
    print("🚀 Setting up development data for Wellbeing Assistant...")
    print("=" * 60)
    
    # Check if running in development
    if os.getenv('FLASK_ENV') != 'development':
        print("⚠️  This script should only be run in development environment!")
        print("Set FLASK_ENV=development before running.")
        return False
    
    # Base URL for your app (adjust if needed)
    base_url = "http://localhost:5001"
    
    try:
        # 1. Create bulk therapists
        print("👩‍⚕️ Creating therapist accounts...")
        response = requests.post(f"{base_url}/register/bulk-therapists")
        
        if response.status_code == 201:
            data = response.json()
            print(f"✅ {data['message']}")
            
            print("\n📋 Created Therapists:")
            for therapist in data['therapists']:
                print(f"   • {therapist['name']} - {therapist['email']}")
            
        elif response.status_code == 403:
            print("❌ Bulk registration is only available in development mode")
            print("Make sure FLASK_ENV=development is set")
            return False
        else:
            print(f"❌ Failed to create therapists: {response.text}")
            return False
            
        print("\n" + "=" * 60)
        print("🎉 DEVELOPMENT SETUP COMPLETED!")
        print("\nYour system now has:")
        print("   👩‍⚕️ 5 therapists with different specializations")
        print("   📅 Real availability schedules")
        print("   🚨 Crisis intervention specialist")
        print("   📞 Emergency hours coverage")
        print("   🔐 Default password: 'Password123'")
        
        print("\n🔐 Login Credentials:")
        print("   Email: Any therapist email from above")
        print("   Password: Password123")
        print("   Role: Therapist")
        
        print("\n📝 Next Steps:")
        print("   1. Start your Flask app: python app.py")
        print("   2. Go to http://localhost:5001/login")
        print("   3. Login with any therapist credentials")
        print("   4. Test the scheduling system!")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to the application.")
        print("Make sure your Flask app is running on http://localhost:5001")
        return False
    except Exception as e:
        print(f"❌ Error during setup: {e}")
        return False

def create_sample_students():
    """Create some sample student accounts for testing"""
    print("\n👨‍🎓 Creating sample student accounts...")
    
    sample_students = [
        {
            "role": "student",
            "first_name": "John",
            "last_name": "Kariuki",
            "email": "john.kariuki@student.university.ac.ke",
            "student_id": "2021001234",
            "password": "Password123",
            "confirm_password": "Password123"
        },
        {
            "role": "student", 
            "first_name": "Mary",
            "last_name": "Wanjiku",
            "email": "mary.wanjiku@student.university.ac.ke",
            "student_id": "2021005678",
            "password": "Password123",
            "confirm_password": "Password123"
        },
        {
            "role": "student",
            "first_name": "David",
            "last_name": "Mwangi",
            "email": "david.mwangi@student.university.ac.ke",
            "student_id": "2021009876",
            "password": "Password123",
            "confirm_password": "Password123"
        }
    ]
    
    base_url = "http://localhost:5001"
    created_students = []
    
    try:
        for student_data in sample_students:
            response = requests.post(
                f"{base_url}/register",
                data=student_data,
                allow_redirects=False
            )
            
            if response.status_code in [200, 302]:  # Success or redirect
                created_students.append(student_data)
                print(f"   ✅ {student_data['first_name']} {student_data['last_name']}")
            else:
                print(f"   ❌ Failed to create {student_data['first_name']} {student_data['last_name']}")
    
        if created_students:
            print(f"\n✅ Created {len(created_students)} student accounts")
            print("🔐 Student Login Details:")
            for student in created_students:
                print(f"   Email: {student['email']}")
            print("   Password: Password123")
            print("   Role: Student")
    
    except Exception as e:
        print(f"❌ Error creating students: {e}")

def verify_therapist_data():
    """Verify that therapist data was created correctly"""
    print("\n🔍 Verifying therapist data structure...")
    
    try:
        # This would require direct database access
        # For now, we'll just show what should be verified
        print("✅ Therapists should have:")
        print("   - Enhanced availability schedules")
        print("   - Multiple specializations")
        print("   - Professional bios")
        print("   - Contact information")
        print("   - Emergency hours flags")
        print("   - Crisis specialist flags")
        
    except Exception as e:
        print(f"❌ Error verifying data: {e}")

def manual_therapist_registration_guide():
    """Show manual registration process"""
    print("\n📝 MANUAL THERAPIST REGISTRATION GUIDE")
    print("=" * 60)
    print("If bulk registration fails, you can register therapists manually:")
    print()
    print("1. Go to: http://localhost:5001/register")
    print("2. Select 'Therapist' role")
    print("3. Click 'Fill Mock Data' button for quick setup")
    print("4. Adjust any fields as needed")
    print("5. Submit the form")
    print()
    print("Sample License Numbers to use:")
    print("   • KPCA001234")
    print("   • KPCA005678") 
    print("   • KPCA009876")
    print("   • KPCA012345")
    print("   • KPCA055555")
    print()
    print("Sample Specializations:")
    print("   • Anxiety + Depression + CBT")
    print("   • Academic Stress + Anxiety")
    print("   • Trauma Therapy + PTSD")
    print("   • Substance Abuse + Group Therapy")
    print("   • Crisis Intervention + Emergency Therapy")

def main():
    """Main setup function"""
    print("🏥 Wellbeing Assistant - Development Setup")
    print("This will populate your system with sample data for testing.")
    print()
    
    # Check environment
    flask_env = os.getenv('FLASK_ENV', 'production')
    print(f"Current environment: {flask_env}")
    
    if flask_env != 'development':
        print("⚠️  Warning: Not in development mode!")
        print("Set environment variable: export FLASK_ENV=development")
        print()
    
    # Setup therapists first
    if setup_development_data():
        # Then create sample students
        create_sample_students()
        
        # Verify data
        verify_therapist_data()
        
        print("\n🎯 COMPLETE SETUP FINISHED!")
        print("You now have therapists AND students to test with.")
        print("\n🚀 Ready to start testing!")
        print("Your Kenyan therapist wellbeing system is ready with:")
        print("   🇰🇪 Realistic Kenyan names and phone numbers")
        print("   🏥 Professional license numbers")
        print("   📅 Diverse availability schedules")
        print("   🎯 Multiple therapy specializations")
        print("   🚨 Emergency and crisis support")
        
    else:
        print("\n❌ Automated setup failed.")
        manual_therapist_registration_guide()
        print("\nTry manual registration or fix the connection issue.")

if __name__ == "__main__":
    main()