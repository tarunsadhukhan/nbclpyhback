from fastapi import APIRouter, Request, HTTPException
from sqlmodel import select, Session
from src.config.db import get_db_names
from src.common.models import Academic_years ,DailyDrawingTransaction,MachineMaster

router = APIRouter()

@router.get("/fetch_joined_data")
def fetch_joined_data(request: Request):
    """
    Dynamically fetches academic_years data from the assigned database.
    """
    try:
        # Get dynamically assigned database engines
        db_engines = get_db_names(request)
        db1_engine = db_engines.get("db1")  # Select first dynamic database (vowsls3)
        
        if not db1_engine:
            raise HTTPException(status_code=500, detail="Database 'db1' not found")

        # Create a session for db1 (vowsls3)
        with Session(db1_engine) as session:
            query = select(Academic_years)  # ORM Query
            print("Executing Query on db1.academic_years:", query)

            result = session.exec(query)
            data = result.all()  # Fetch all records

        return {"data": data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/fetch_joined_datas")
def fetch_joined_data(request: Request):
    """
    Fetches data from `db1.daily_drawing_transaction` and `db2.machine_master` 
    with a filter for `tran_date = '2025-02-28'`.
    """
    try:
        # Get dynamically assigned database engines
        db_engines = get_db_names(request)
        db1_engine = db_engines.get("db1")  # First database (vowsls3)
        db2_engine = db_engines.get("db2")  # Second database

        if not db1_engine or not db2_engine:
            raise HTTPException(status_code=500, detail="Databases 'db1' or 'db2' not found")

        # Query data from `db1.daily_drawing_transaction` with date filter
        with Session(db2_engine) as session_db2:
            query_db2 = select(DailyDrawingTransaction).where(DailyDrawingTransaction.tran_date == "2025-02-28")
            print("Executing Query on db1.daily_drawing_transaction:", query_db2)
            result_db2 = session_db2.exec(query_db2)
            data_db2 = result_db2.all()  # Fetch filtered records

        # Query data from `db2.machine_master`
        with Session(db1_engine) as session_db1:
            query_db1 = select(MachineMaster)
            print("Executing Query on db2.machine_master:", query_db1)
            result_db1 = session_db1.exec(query_db1)
            data_db1 = result_db1.all()  # Fetch all records

        # Convert machine master data into a lookup dictionary
        machine_dict = {mm.mechine_id: mm for mm in data_db1}

        # Perform a manual LEFT JOIN in Python
        joined_data = []
        for ddt in data_db2:
            machine_data = machine_dict.get(ddt.drg_mc_id)  # Match drg_mc_id with mechine_id
            joined_data.append({
                "tran_date": ddt.tran_date,
                "spell": ddt.spell,
                "drg_mc_id": ddt.drg_mc_id,
                "diff_meter": ddt.diff_meter,
                "mech_code": machine_data.mech_code if machine_data else None,
                "mechine_name": machine_data.mechine_name if machine_data else None,
            })

        return {"data": joined_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
