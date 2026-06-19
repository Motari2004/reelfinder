"""
Google Drive Token Generator
Standalone script to generate drive_token.pickle from credentials.json
"""

import os
import pickle
import base64
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive']

def generate_token():
    """Generate drive_token.pickle from credentials.json"""
    
    print("=" * 60)
    print("🔑 Google Drive Token Generator")
    print("=" * 60)
    
    # Check if credentials.json exists
    if not os.path.exists('credentials.json'):
        print("\n❌ ERROR: credentials.json not found!")
        print("📌 Please place your credentials.json file in this directory.")
        print("📌 You can download it from Google Cloud Console:")
        print("   https://console.cloud.google.com/apis/credentials")
        return False
    
    try:
        print("\n📂 Found credentials.json")
        print("🔄 Starting OAuth flow...")
        
        # Create the flow
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        
        # Run the local server
        print("🌐 Opening browser for authentication...")
        creds = flow.run_local_server(port=0)
        
        print("✅ Authentication successful!")
        
        # Save the token
        with open('drive_token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        
        print("💾 Token saved to: drive_token.pickle")
        print("📌 This file should NOT be committed to git!")
        
        # Encode for Render
        with open('drive_token.pickle', 'rb') as f:
            token_data = f.read()
            encoded = base64.b64encode(token_data).decode('utf-8')
        
        print("\n" + "=" * 60)
        print("📤 BASE64 ENCODED TOKEN (for Render)")
        print("=" * 60)
        print("\n" + encoded + "\n")
        print("=" * 60)
        print("📌 Copy the above base64 string to Render as:")
        print("   GOOGLE_DRIVE_TOKEN = <paste here>")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n📌 Troubleshooting:")
        print("   - Make sure credentials.json is valid")
        print("   - Check that Drive API is enabled")
        print("   - Try running with: python generate_token.py")
        return False

def test_token():
    """Test if the token works"""
    
    print("\n" + "=" * 60)
    print("🧪 Testing Token...")
    print("=" * 60)
    
    try:
        if os.path.exists('drive_token.pickle'):
            with open('drive_token.pickle', 'rb') as token:
                creds = pickle.load(token)
            
            # Check if token is valid
            if creds and creds.valid:
                print("✅ Token is valid!")
                return True
            elif creds and creds.expired and creds.refresh_token:
                print("🔄 Token expired, refreshing...")
                creds.refresh(Request())
                with open('drive_token.pickle', 'wb') as token:
                    pickle.dump(creds, token)
                print("✅ Token refreshed and saved!")
                return True
            else:
                print("❌ Token is invalid")
                print("📌 Please regenerate the token")
                return False
        else:
            print("❌ No token file found")
            print("📌 Please run: python generate_token.py")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def encode_existing_token():
    """Encode an existing drive_token.pickle for Render"""
    
    print("\n" + "=" * 60)
    print("📤 Encode Existing Token for Render")
    print("=" * 60)
    
    if not os.path.exists('drive_token.pickle'):
        print("❌ No drive_token.pickle found!")
        print("📌 Please generate a token first: python generate_token.py")
        return False
    
    try:
        with open('drive_token.pickle', 'rb') as f:
            token_data = f.read()
            encoded = base64.b64encode(token_data).decode('utf-8')
        
        print("\n🔑 Encoded Token:")
        print("=" * 60)
        print(encoded)
        print("=" * 60)
        print("\n📌 Copy this to Render as GOOGLE_DRIVE_TOKEN")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main menu"""
    print("\n📋 Options:")
    print("  1. Generate new token from credentials.json")
    print("  2. Test existing token")
    print("  3. Encode existing token for Render")
    print("  4. All (Generate, Test, Encode)")
    
    choice = input("\nSelect option (1-4): ").strip()
    
    if choice == "1":
        generate_token()
    elif choice == "2":
        test_token()
    elif choice == "3":
        encode_existing_token()
    elif choice == "4":
        generate_token()
        test_token()
        encode_existing_token()
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()