import gdown
import os
import time

# --- 1. MAPPING GOOGLE DRIVE FILE IDs TO YOUR LOCAL NAMES ---
# To get the ID: Right-click file in Drive -> Share -> Copy Link. 
# The ID is the string between /d/ and /view
file_mapping = {
    "1_ZskAZ_-Zk2DBvCm03LRKmG9kVRa56Ni": "data_mm_connect.csv",
    "1-0M1LS7C9VpZqb9yuFEnbQ_ABvKYiV1o": "data_issuing.csv",
    "1-f2Z00Y2I65MyuBLVnriMfYilXzXVyzh": "data_bridge_other.csv",
    "1ubyc_vzCM6QIIqfXM3xxw-HGH0VRcSgL": "gross_data_mm_connect.csv",
    "1A56KbIpWgK3xdYItEBn1JZB65VS5lAGU": "gross_data_issuing.csv",
    "10fufMF52IhxqkrV6cA8TMNOnZ_x6wz6i": "gross_data_bridge_other.csv"
}
def download_latest_data():
    print("🚀 Starting FORCE refresh from Google Drive...")
    
    for file_id, local_name in file_mapping.items():
        # Remove old file if it exists to force a fresh timestamp
        if os.path.exists(local_name):
            os.remove(local_name)
            print(f"🗑️ Deleted old {local_name}")

        url = f'https://drive.google.com/uc?id={file_id}'
        
        try:
            # Use gdown to download directly
            gdown.download(url, local_name, quiet=False)
            
            # Final check: did it actually create the file?
            if os.path.exists(local_name):
                print(f"✅ Created NEW {local_name} - Size: {os.path.getsize(local_name)} bytes")
            else:
                print(f"❌ Error: {local_name} was not created.")
                
        except Exception as e:
            print(f"❌ Failed to download {local_name}: {e}")
        
        time.sleep(2)

    print("\n✨ Process finished. Check your folder now!")

if __name__ == "__main__":
    download_latest_data()