import gdown
import os

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
    print("🚀 Starting secure data pull from Google Drive...")
    
    for file_id, local_name in file_mapping.items():
        url = f'https://drive.google.com/uc?id={file_id}'
        print(f"📥 Downloading {local_name}...")
        
        try:
            # This will overwrite the existing local file
            gdown.download(url, local_name, quiet=False, fuzzy=True)
            print(f"✅ Successfully updated {local_name}")
        except Exception as e:
            print(f"❌ Failed to download {local_name}: {e}")
        
        # Wait 2 seconds to avoid Google security blocks
        time.sleep(2)

    print("\n✨ All files processed. Check your folder timestamps!")

if __name__ == "__main__":
    download_latest_data()