import os
import sys
from sqlalchemy import create_engine, MetaData, text

def migrate_db():
    print("Starting migration from SQLite to PostgreSQL...")
    
    sqlite_uri = f'sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), "lms.db")}'
    postgres_uri = 'postgresql://admin:2eeVJ2Z6C2vu4ltHXdBowKyr8ZRUm43A@dpg-da7qro710e5c73eul9k0-a.oregon-postgres.render.com/lms_3if2'
    
    os.environ['DATABASE_URL'] = postgres_uri
    
    # Patch init_db_and_seed to do nothing
    import app.seed
    app.seed.init_db_and_seed = lambda app: print("Skipped seeding")
    
    from app import create_app
    from app.models import db
    
    flask_app = create_app()
    with flask_app.app_context():
        print("Creating tables in PostgreSQL if they don't exist...")
        db.create_all()
        dest_metadata = db.metadata
        dest_engine = db.engine
        
        src_engine = create_engine(sqlite_uri)
        src_metadata = MetaData()
        src_metadata.reflect(bind=src_engine)
        
        print("Clearing existing data in PostgreSQL (using TRUNCATE CASCADE)...")
        with dest_engine.begin() as dest_conn:
            for table in dest_metadata.sorted_tables:
                try:
                    dest_conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
                except Exception as e:
                    pass
        
        # We need to insert in topological order (parent tables first)
        # sorted_tables is topologically sorted
        for table in dest_metadata.sorted_tables:
            if table.name not in src_metadata.tables:
                continue
                
            src_table = src_metadata.tables[table.name]
            print(f"Migrating table: {table.name}...")
            
            with src_engine.connect() as src_conn:
                rows = src_conn.execute(src_table.select()).fetchall()
                
            if not rows:
                print(f" - No data to migrate for {table.name}")
                continue
                
            columns = src_table.columns.keys()
            data = [dict(row._mapping) for row in rows]
            
            chunk_size = 1000
            with dest_engine.begin() as dest_conn:
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i + chunk_size]
                    dest_conn.execute(table.insert(), chunk)
                    
            print(f" - Migrated {len(data)} rows for {table.name}")
            
        print("Migration completed successfully!")

if __name__ == '__main__':
    migrate_db()
