import requests
from bs4 import BeautifulSoup
from getpass import getpass

LOGIN_URL = "https://lms.umt.edu.pk/login/index.php"   # Moodle mein GET aur POST dono isi par

username = input("Username: ")
password = getpass("Password: ")

s = requests.Session()

# 1. Login page kholo aur hidden token uthao
r = s.get(LOGIN_URL)
soup = BeautifulSoup(r.text, "html.parser")
token = soup.find("input", {"name": "logintoken"})

# 2. Form submit karo
payload = {
    "anchor": "",
    "logintoken": token["value"] if token else "",
    "username": username,
    "password": password,
}
r = s.post(LOGIN_URL, data=payload)   # requests 303 redirects khud follow kar leta hai

# 3. Check karo
print("Final URL:", r.url)
print("Login hua?", "/login/" not in r.url)

# Dashboard ka title print karo, proof ke liye
soup = BeautifulSoup(r.text, "html.parser")
print("Page title:", soup.title.string if soup.title else "?")