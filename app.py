import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import time

# ========== CONFIGURATION ==========
GOOGLE_SHEET_ID = "1jtUc0olB338B9TLE6f3w8AC7CtUKqwT7Nl4_3I7edd0"
DRIVE_FOLDER_ID = "1zH8HYwXp1qPTYksGMXfcOlj04hJ0SNKI"
PRODUCTS = ["Donut Cake", "Chocochip Muffin", "Banana Muffin", "Brownie"]

# ========== GOOGLE SHEETS & DRIVE AUTH ==========
@st.cache_resource
def init_google():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["GOOGLE_SERVICE_ACCOUNT"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    try:
        user_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet("users")
    except gspread.exceptions.WorksheetNotFound:
        user_sheet = client.open_by_key(GOOGLE_SHEET_ID).add_worksheet("users", rows=100, cols=5)
        user_sheet.append_row(["Username", "Password", "Role", "Employee Name", "Distributors"])

    drive_service = build("drive", "v3", credentials=creds)
    drive_service.files().get(
        fileId=DRIVE_FOLDER_ID,
        fields="id,name",
        supportsAllDrives=True
    ).execute()

    return sheet, user_sheet, creds

sheet, user_sheet, creds = init_google()

# ========== SHOP LIST LOADER ==========
@st.cache_data(ttl=60)
def get_shop_list(emp_name, distributor, refresh_token):
    try:
        orders_df = pd.DataFrame(sheet.get_all_records())
    except Exception:
        return []
    if orders_df.empty:
        return []
    filtered_df = orders_df[
        (orders_df.get("Employee Name") == emp_name) &
        (orders_df.get("Distributor") == distributor)
    ]
    existing_shops = []
    seen = set()
    for shop in filtered_df.get("Shop Name", pd.Series()).dropna():
        shop_clean = str(shop).strip()
        shop_lower = shop_clean.lower()
        if shop_lower not in seen:
            seen.add(shop_lower)
            existing_shops.append(shop_clean)
    return sorted(existing_shops)

# ========== LOGIN ==========
def login(username, password):
    users = pd.DataFrame(user_sheet.get_all_records())
    match = users[(users["Username"] == username) & (users["Password"] == password)]
    if not match.empty:
        return match.iloc[0].to_dict()
    return None

if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    st.title("🔑 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user_data = login(username, password)
        if user_data:
            st.session_state.user = user_data
            st.rerun()
        else:
            st.error("❌ Invalid username or password")
else:
    role = st.session_state.user["Role"]
    emp_name = st.session_state.user["Employee Name"]

    if st.button("Logout"):
        st.session_state.user = None
        st.rerun()

    # ========== ADMIN ==========
    if role.lower() == "admin":
        st.title("🛠 Admin Panel")
        uploaded_file = st.file_uploader("Upload Employee Mapping", type=["xlsx", "csv"])
        if uploaded_file:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            df = df.fillna("")
            required_cols = ["Username", "Password", "Role", "Employee Name", "Distributors"]
            if all(col in df.columns for col in required_cols):
                user_sheet.clear()
                user_sheet.append_row(required_cols)
                for _, row in df.iterrows():
                    user_sheet.append_row(list(row[required_cols]))
                st.success("✅ User mapping updated successfully!")
            else:
                st.error(f"❌ Missing required columns. Need: {required_cols}")

    # ========== EMPLOYEE ==========
    elif role.lower() == "employee":
        st.title("🍩 DBs Order Form")

        distributors_list = []
        if st.session_state.user["Distributors"]:
            distributors_list = [d.strip() for d in st.session_state.user["Distributors"].split(",")]

        # Distributor selection
        distributor = st.selectbox("🏪 Distributor", distributors_list, key="distributor")

        # Shop list
        shop_list = get_shop_list(emp_name, distributor, st.session_state.get("shops_refresh_token", 0))

        # Shop name selector
        shop_name = st.selectbox(
            "📍 Shop Name (type to search or add new)",
            options=[""] + shop_list,
            index=0,
            key="shop_select",
            placeholder="Start typing shop name..."
        )
        if not shop_name:
            shop_name = st.text_input("Enter New Shop Name", key="shop_new")

        # Two refresh buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh Shops"):
                st.session_state["shops_refresh_token"] = time.time()
                st.rerun()
        with col2:
            if st.button("🧹 Clear Form"):
                preserve_keys = ["user", "shops_refresh_token"]
                for key in list(st.session_state.keys()):
                    if key not in preserve_keys:
                        del st.session_state[key]
                st.rerun()

        # Upload shop photo
        photo = st.file_uploader("📷 Upload Shop Photo", type=["jpg", "jpeg", "png"], key="photo")

        # Beat Area
        beat_area = st.text_input("🗺️ Beat Area", key="beat_area")

        # Order Date
        order_date = st.date_input("📅 Order Date", value=datetime.today(), key="order_date")

        # Last Visited Date
        last_visit = st.date_input("📅 Last Visited Date", key="last_visit")

        # No. of Visits
        num_visits = st.number_input("🔁 No. of Visits", min_value=1, step=1, key="num_visits")

        # Margin
        margin = st.number_input("💰 Margin (%)", min_value=0.0, max_value=100.0, value=20.0, key="margin")

        # Product matrix
        st.subheader("📦 Product Details")
        product_entries = []
        for product in PRODUCTS:
            cols = st.columns(3)
            with cols[0]:
                st.markdown(f"**{product}**")
            with cols[1]:
                qty = st.number_input(f"Qty", min_value=0, step=1, key=f"qty_{product}")
            with cols[2]:
                soh = st.number_input(f"SOH", min_value=0, step=1, key=f"soh_{product}")
            if qty > 0 or soh > 0:
                product_entries.append({"SKU": product, "QTY": qty, "SOH": soh})

        # Remarks
        remarks = st.text_area("📝 Remarks (Optional)", key="remarks")

        # Submit Order
        if st.button("📤 Submit Order"):
            if not distributor:
                st.error("❌ Distributor is required.")
            elif not shop_name:
                st.error("❌ Shop Name is required.")
            elif not product_entries:
                st.error("❌ Enter at least one product with Qty or SOH.")
            elif not photo:
                st.error("❌ Upload a shop photo.")
            else:
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    drive_url = "Not Uploaded"

                    try:
                        drive_service = build("drive", "v3", credentials=creds)
                        photo.seek(0)
                        media = MediaIoBaseUpload(io.BytesIO(photo.read()), mimetype=photo.type)
                        file_metadata = {
                            "name": f"{shop_name.replace(' ', '_')}_{timestamp.replace(':', '-').replace(' ', '_')}.jpg",
                            "parents": [DRIVE_FOLDER_ID]
                        }
                        uploaded = drive_service.files().create(
                            body=file_metadata,
                            media_body=media,
                            fields="webViewLink,id",
                            supportsAllDrives=True
                        ).execute()
                        drive_url = uploaded.get("webViewLink", "Not Available")
                    except Exception as e:
                        st.warning(f"⚠️ Drive upload failed: {e}")
                        drive_url = "Upload Failed"

                    success_count = 0
                    for entry in product_entries:
                        row = [
                            timestamp,
                            order_date.strftime("%Y-%m-%d"),
                            emp_name,
                            distributor,
                            shop_name,
                            margin,
                            beat_area,
                            entry["SKU"],
                            entry["QTY"],
                            entry["SOH"],
                            drive_url,
                            remarks,
                            last_visit.strftime("%Y-%m-%d"),
                            int(num_visits)
                        ]
                        sheet.append_row(row)
                        success_count += 1

                    st.session_state['shops_refresh_token'] = time.time()

                    if success_count > 0:
                        st.success(f"✅ Order submitted! {success_count} product(s) added.")
                        if drive_url not in ["Not Uploaded", "Upload Failed"]:
                            st.markdown(f"[📸 View Photo]({drive_url})")
                    else:
                        st.error("❌ No products were submitted.")

                except Exception as e:
                    st.error(f"❌ Submission failed: {e}")
