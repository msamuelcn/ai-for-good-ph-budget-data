import sqlalchemy
from google.cloud.alloydb.connector import Connector, IPTypes

# Initialize Connector
connector = Connector()


def getconn():
    conn = connector.connect(
        "projects/sam-hackathon-projects/locations/asia-southeast1/clusters/free-trial-cluster/instances/primary",
        "pg8000",  # Use psycopg (no '2') here
        user="marksamuel.nicasio@gmail.com",
        password=r"",
        db="postgres",
        enable_iam_auth=True,
        ip_type=IPTypes.PUBLIC,
    )
    return conn


engine = sqlalchemy.create_engine(
    "postgresql+pg8000://",  # Use pg8000 (no '2') here
    creator=getconn,
)


# Example: Use the engine to load your Parquet file via Pandas
# import pandas as pd
# df = pd.read_parquet('~/ai-for-good-budget-drift/your_file.parquet')
# df.to_sql('your_table', engine, if_exists='append', index=False)

with engine.connect() as conn:
    result = conn.execute(sqlalchemy.text("SELECT CURRENT_USER;"))
    print(f"Connected as: {result.fetchone()[0]}")
