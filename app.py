import psycopg2
from fastapi import FastAPI

app = FastAPI()

# Replace with your database credentials
DB_HOST = 'localhost'
DB_NAME = 'Misreport'
DB_USER = 'postgres'
DB_PASSWORD = 'Pranjal@241'

conn = psycopg2.connect(
    host=DB_HOST,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)

cur = conn.cursor()

def get_user_mis_report(idpId: str):
    # Dynamic SQL query to retrieve data based on idpId
    cur.execute("""
        SELECT *
        FROM table1
        WHERE idpId = %s
        UNION ALL
        SELECT *
        FROM table2
        WHERE idpId = %s
        UNION ALL
        SELECT *
        FROM table3
        WHERE idpId = %s
    """, (idpId, idpId, idpId))
    data = cur.fetchall()
    return data

@app.get("/user_mis_report")
def get_user_mis_report_endpoint(idpId: str):
    data = get_user_mis_report(idpId)
    return {"data": data}

@app.get("/user_mis_report")
def get_user_mis_report_endpoint():
    cur.execute("SELECT * FROM your_table_name")
    data = cur.fetchall()
    return {"data": data}