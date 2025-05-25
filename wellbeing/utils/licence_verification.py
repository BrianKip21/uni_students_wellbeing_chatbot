"""
Kenya-focused License Verification System for Development
Supports automatic therapist approval with mock data for testing
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class KenyaLicenseVerifier:
    """
    License verification system for Kenya-based therapist registration
    Uses mock data for development, easily replaceable with real APIs later
    """
    
    def __init__(self):
        # Mock license database for development
        self.mock_licenses = {
            # Kenya Psychology Board
            'KEN001': {
                'holder_name': 'Dr. Grace Wanjiku',
                'license_type': 'Clinical Psychology',
                'country': 'Kenya',
                'board': 'Kenya Psychology Board',
                'status': 'Active',
                'issue_date': '2020-03-15',
                'expiry_date': '2025-03-15',
                'specializations': ['Trauma Therapy', 'Anxiety Disorders'],
                'verification_score': 95
            },
            'KEN002': {
                'holder_name': 'Dr. James Mwangi',
                'license_type': 'Counseling Psychology',
                'country': 'Kenya',
                'board': 'Kenya Psychology Board',
                'status': 'Active',
                'issue_date': '2019-07-20',
                'expiry_date': '2024-07-20',
                'specializations': ['Marriage Counseling', 'Family Therapy'],
                'verification_score': 92
            },
            'KPSYC123': {
                'holder_name': 'Dr. Mary Njeri',
                'license_type': 'Clinical Psychology',
                'country': 'Kenya',
                'board': 'Kenya Psychology and Counseling Association',
                'status': 'Active',
                'issue_date': '2021-01-10',
                'expiry_date': '2026-01-10',
                'specializations': ['Child Psychology', 'ADHD Treatment'],
                'verification_score': 98
            },
            
            # International licenses for global expansion testing
            'PSY12345': {
                'holder_name': 'Dr. Sarah Johnson',
                'license_type': 'Licensed Clinical Social Worker',
                'country': 'United States',
                'state': 'California',
                'board': 'California Board of Psychology',
                'status': 'Active',
                'issue_date': '2018-09-12',
                'expiry_date': '2025-09-12',
                'specializations': ['Depression', 'Anxiety', 'PTSD'],
                'verification_score': 90
            },
            'UK123456': {
                'holder_name': 'Dr. Emma Thompson',
                'license_type': 'Chartered Psychologist',
                'country': 'United Kingdom',
                'board': 'Health and Care Professions Council',
                'status': 'Active',
                'issue_date': '2019-11-08',
                'expiry_date': '2024-11-08',
                'specializations': ['Cognitive Behavioral Therapy'],
                'verification_score': 88
            },
            'CAN789': {
                'holder_name': 'Dr. David Laurent',
                'license_type': 'Registered Psychologist',
                'country': 'Canada',
                'province': 'Ontario',
                'board': 'College of Psychologists of Ontario',
                'status': 'Active',
                'issue_date': '2020-05-22',
                'expiry_date': '2025-05-22',
                'specializations': ['Addiction Counseling'],
                'verification_score': 93
            },
            'SA456789': {
                'holder_name': 'Dr. Nomsa Dlamini',
                'license_type': 'Clinical Psychologist',
                'country': 'South Africa',
                'board': 'Health Professions Council of South Africa',
                'status': 'Active',
                'issue_date': '2021-02-14',
                'expiry_date': '2026-02-14',
                'specializations': ['Trauma Therapy', 'PTSD'],
                'verification_score': 96
            },
            
            # Invalid/Expired licenses for testing
            'EXPIRED123': {
                'holder_name': 'Dr. Test Expired',
                'license_type': 'Clinical Psychology',
                'country': 'Kenya',
                'board': 'Kenya Psychology Board',
                'status': 'Expired',
                'issue_date': '2015-01-01',
                'expiry_date': '2020-01-01',
                'specializations': ['General Practice'],
                'verification_score': 0
            },
            'SUSPENDED456': {
                'holder_name': 'Dr. Test Suspended',
                'license_type': 'Counseling Psychology',
                'country': 'Kenya',
                'board': 'Kenya Psychology Board',
                'status': 'Suspended',
                'issue_date': '2018-06-15',
                'expiry_date': '2023-06-15',
                'specializations': ['General Practice'],
                'verification_score': 0
            }
        }
        
        # License pattern recognition for different countries
        self.license_patterns = {
            'Kenya': [
                r'^KEN\d{3}$',  # KEN001, KEN002, etc.
                r'^KPSYC\d{3}$',  # KPSYC123, etc.
                r'^KPB\d{4}$',  # Kenya Psychology Board format
            ],
            'United States': [
                r'^PSY\d{5}$',  # PSY12345
                r'^LCSW\d{4}$',  # Licensed Clinical Social Worker
                r'^MFT\d{4}$',   # Marriage and Family Therapist
            ],
            'United Kingdom': [
                r'^UK\d{6}$',   # UK123456
                r'^HCPC\d{5}$', # Health and Care Professions Council
            ],
            'Canada': [
                r'^CAN\d{3}$',  # CAN789
                r'^CPO\d{4}$',  # College of Psychologists Ontario
            ],
            'South Africa': [
                r'^SA\d{6}$',   # SA456789
                r'^HPCSA\d{5}$', # Health Professions Council SA
            ]
        }
    
    def verify_license(self, license_number: str, country: str = 'Kenya') -> Dict:
        """
        Verify a license number and return verification results
        
        Args:
            license_number: The license number to verify
            country: Country where the license was issued
            
        Returns:
            Dictionary with verification results
        """
        try:
            # Clean license number
            license_number = license_number.strip().upper()
            
            # Step 1: Format validation
            format_valid = self._validate_license_format(license_number, country)
            
            # Step 2: Database lookup (mock for development)
            license_data = self._lookup_license(license_number)
            
            # Step 3: Status verification
            status_check = self._verify_license_status(license_data)
            
            # Step 4: Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                format_valid, license_data, status_check
            )
            
            # Step 5: Auto-approval decision
            auto_approve = confidence_score >= 70
            
            return {
                'license_number': license_number,
                'country': country,
                'valid': license_data is not None,
                'format_valid': format_valid,
                'status_check': status_check,
                'confidence_score': confidence_score,
                'auto_approve': auto_approve,
                'license_data': license_data,
                'verification_timestamp': datetime.now().isoformat(),
                'verification_method': 'mock_database',  # Will be 'api_lookup' in production
                'next_steps': self._get_next_steps(auto_approve, license_data)
            }
            
        except Exception as e:
            return {
                'license_number': license_number,
                'country': country,
                'valid': False,
                'error': str(e),
                'confidence_score': 0,
                'auto_approve': False,
                'verification_timestamp': datetime.now().isoformat()
            }
    
    def _validate_license_format(self, license_number: str, country: str) -> bool:
        """Validate license number format based on country patterns"""
        patterns = self.license_patterns.get(country, [])
        
        for pattern in patterns:
            if re.match(pattern, license_number):
                return True
        
        return False
    
    def _lookup_license(self, license_number: str) -> Optional[Dict]:
        """Look up license in database (mock implementation)"""
        return self.mock_licenses.get(license_number)
    
    def _verify_license_status(self, license_data: Optional[Dict]) -> Dict:
        """Verify the current status of the license"""
        if not license_data:
            return {
                'valid': False,
                'reason': 'License not found',
                'status': 'not_found'
            }
        
        status = license_data.get('status', '').lower()
        expiry_date = license_data.get('expiry_date')
        
        # Check if expired
        if expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d')
            if expiry < datetime.now():
                return {
                    'valid': False,
                    'reason': f'License expired on {expiry_date}',
                    'status': 'expired'
                }
        
        # Check status
        if status == 'active':
            return {
                'valid': True,
                'reason': 'License is active and valid',
                'status': 'active'
            }
        elif status == 'suspended':
            return {
                'valid': False,
                'reason': 'License is currently suspended',
                'status': 'suspended'
            }
        elif status == 'revoked':
            return {
                'valid': False,
                'reason': 'License has been revoked',
                'status': 'revoked'
            }
        else:
            return {
                'valid': False,
                'reason': f'Unknown license status: {status}',
                'status': 'unknown'
            }
    
    def _calculate_confidence_score(self, format_valid: bool, 
                                  license_data: Optional[Dict], 
                                  status_check: Dict) -> int:
        """Calculate confidence score for auto-approval decision"""
        score = 0
        
        # Format validation (20 points)
        if format_valid:
            score += 20
        
        # License found in database (30 points)
        if license_data:
            score += 30
            
            # Additional points based on license data quality
            if license_data.get('verification_score'):
                score += min(license_data['verification_score'] * 0.3, 30)
        
        # Status verification (20 points)
        if status_check.get('valid'):
            score += 20
        
        return min(int(score), 100)
    
    def _get_next_steps(self, auto_approve: bool, license_data: Optional[Dict]) -> List[str]:
        """Get next steps based on verification results"""
        if auto_approve:
            return [
                "✅ License verified successfully",
                "🎉 Account will be automatically approved",
                "📧 You'll receive a confirmation email shortly",
                "🚀 You can start accepting students immediately"
            ]
        else:
            steps = ["❌ Automatic verification failed"]
            
            if not license_data:
                steps.extend([
                    "📋 Your license will be manually reviewed",
                    "📞 Our team may contact you for verification",
                    "⏰ Manual review typically takes 1-2 business days"
                ])
            else:
                status = license_data.get('status', '').lower()
                if status in ['expired', 'suspended', 'revoked']:
                    steps.extend([
                        f"⚠️ License status: {status.title()}",
                        "📞 Please contact support to resolve this issue",
                        "📄 You may need to provide updated documentation"
                    ])
            
            return steps
    
    def get_supported_countries(self) -> List[Dict]:
        """Get list of supported countries for license verification"""
        return [
            {
                'code': 'KE',
                'name': 'Kenya',
                'description': 'Kenya Psychology Board & KPCA',
                'primary': True,
                'sample_format': 'KEN001, KPSYC123'
            },
            {
                'code': 'US',
                'name': 'United States',
                'description': 'State Psychology Boards',
                'primary': False,
                'sample_format': 'PSY12345, LCSW1234'
            },
            {
                'code': 'GB',
                'name': 'United Kingdom',
                'description': 'HCPC Registration',
                'primary': False,
                'sample_format': 'UK123456, HCPC12345'
            },
            {
                'code': 'CA',
                'name': 'Canada',
                'description': 'Provincial Psychology Colleges',
                'primary': False,
                'sample_format': 'CAN789, CPO1234'
            },
            {
                'code': 'ZA',
                'name': 'South Africa',
                'description': 'HPCSA Registration',
                'primary': False,
                'sample_format': 'SA456789, HPCSA12345'
            }
        ]
    
    def batch_verify_licenses(self, licenses: List[Tuple[str, str]]) -> List[Dict]:
        """Verify multiple licenses at once"""
        results = []
        
        for license_number, country in licenses:
            result = self.verify_license(license_number, country)
            results.append(result)
        
        return results
    
    def get_verification_stats(self, results: List[Dict]) -> Dict:
        """Get statistics from verification results"""
        total = len(results)
        if total == 0:
            return {}
        
        auto_approved = sum(1 for r in results if r.get('auto_approve'))
        manual_review = total - auto_approved
        
        avg_confidence = sum(r.get('confidence_score', 0) for r in results) / total
        
        countries = {}
        for result in results:
            country = result.get('country', 'Unknown')
            countries[country] = countries.get(country, 0) + 1
        
        return {
            'total_verifications': total,
            'auto_approved': auto_approved,
            'manual_review': manual_review,
            'auto_approval_rate': (auto_approved / total) * 100,
            'average_confidence': round(avg_confidence, 1),
            'countries_processed': countries,
            'top_country': max(countries.items(), key=lambda x: x[1])[0] if countries else None
        }


# Flask integration example
def integrate_with_flask_app(app):
    """
    Example of how to integrate the license verifier with your Flask app
    """
    from flask import request, jsonify
    
    verifier = KenyaLicenseVerifier()
    
    @app.route('/api/verify-license', methods=['POST'])
    def verify_license_endpoint():
        """API endpoint for license verification"""
        try:
            data = request.get_json()
            license_number = data.get('license_number')
            country = data.get('country', 'Kenya')
            
            if not license_number:
                return jsonify({'error': 'License number is required'}), 400
            
            result = verifier.verify_license(license_number, country)
            return jsonify(result)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/supported-countries', methods=['GET'])
    def get_supported_countries():
        """API endpoint to get supported countries"""
        return jsonify(verifier.get_supported_countries())


# Usage example for testing
if __name__ == "__main__":
    # Test the verifier
    verifier = KenyaLicenseVerifier()
    
    # Test cases
    test_licenses = [
        ('KEN001', 'Kenya'),  # Should auto-approve
        ('KPSYC123', 'Kenya'),  # Should auto-approve  
        ('EXPIRED123', 'Kenya'),  # Should reject
        ('PSY12345', 'United States'),  # Should auto-approve
        ('INVALID999', 'Kenya'),  # Should reject
    ]
    
    print("=== License Verification Test Results ===\n")
    
    results = []
    for license_num, country in test_licenses:
        print(f"Testing: {license_num} ({country})")
        result = verifier.verify_license(license_num, country)
        results.append(result)
        
        print(f"  ✅ Valid: {result['valid']}")
        print(f"  🎯 Confidence: {result['confidence_score']}%")
        print(f"  🚀 Auto-approve: {result['auto_approve']}")
        
        if result.get('license_data'):
            data = result['license_data']
            print(f"  👤 Holder: {data.get('holder_name')}")
            print(f"  🏥 Specializations: {', '.join(data.get('specializations', []))}")
        
        print()
    
    # Stats
    stats = verifier.get_verification_stats(results)
    print("=== Verification Statistics ===")
    print(f"Auto-approval rate: {stats['auto_approval_rate']:.1f}%")
    print(f"Average confidence: {stats['average_confidence']}%")
    print(f"Countries processed: {list(stats['countries_processed'].keys())}")