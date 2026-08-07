from fastapi import APIRouter, Depends, Query, HTTPException,Request
#from fastapi import Column, Integer, String, Text, DateTime, Boolean, JSON
import json
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from src.config.database import get_db
from src.common.schemas import CountrySchema,StateSchema,CountryResponseSchema,ModuleSchema
from src.common.schemas import ModuleResponseSchema,StateResponseSchema,ContactFormSchema
from src.common.utils import execute_query, create_response
from src.common.models import ConOrgMaster
import logging
from src.common.utils import parse_json_body
router = APIRouter()

# ✅ Fetch All Countries API

logging.basicConfig(
    level=logging.INFO,  # ✅ Set log level (INFO, DEBUG, ERROR, etc.)
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # ✅ Print logs to console
    ],
)


#logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.get("/modules",response_model=ModuleResponseSchema)
def get_countries(db: Session = Depends(get_db)):
    """
    Fetch all countries.
    """
    try:
        query = "SELECT con_module_id, con_module_name FROM con_module_masters"
        
    
        modules = execute_query(db, query)
        return {"data": modules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    
@router.post("/savecontactforms")
def submit_contact_form(form: ContactFormSchema, db: Session = Depends(get_db)):
    """
    Receives form submission from frontend and saves it to the database.
    """
    print('form',form)
    try:
        query = """
            INSERT INTO vowconsole3.con_org_master (con_org_name, con_org_address)
            VALUES ('abcd', 'uuuu')"""

        params = {
            "name": form.name,
            "address": form.address 
        }
        print('params',params,query)
        execute_query(db, query, commit=True)
        print((f"Database Error: {e}") )
        return {"message": "Form submitted successfully!"}
        logger.error(f"Database Error: {e}")  # ✅ Log error details

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting form: {str(e)}")
  
    
@router.post("/savecontactform_1")
def submit_contact_form(request: Request, db: Session = Depends(get_db)):
    """
    Receives form submission from frontend and saves it to the database.
    """
    try:
        # ✅ Extract form data manually from JSON request
        form_data = parse_json_body(request)
        name = form_data.get("name")
        address = form_data.get("address")

        logger.info(f"Received Data: name={name}, address={address}")  # ✅ Log received data

        # ✅ Check if required fields are missing
        if not name or not address:
            raise HTTPException(status_code=400, detail="Missing 'name' or 'address' field")

        # ✅ Use parameterized query to prevent SQL injection
        query = text("""
            INSERT INTO con_org_master (con_org_name, con_org_address, con_org_pincode, con_org_state_id, con_org_email_id, 
            con_org_mobile, con_org_contact_person, con_org_shortname, con_org_remarks, active, con_org_master_status, 
            created_date_time, con_modules_selected)
            VALUES (:name, :address, :pincode, :state, :email, :mobile, :contact_person, :org_shr_name, :message, 1, 1,
            NOW(), :modules)
        """)

        params = {
            "name": name,
            "email": form_data.get("email"),
            "message": form_data.get("message"),
            "address": address,
            "pincode": form_data.get("pincode"),
            "state": form_data.get("state"),  # ✅ Convert array to string
            "country": form_data.get("country"),  # ✅ Convert array to string
            "mobile": form_data.get("mobile"),
            "contact_person": form_data.get("contactPerson"),
            "org_shr_name": form_data.get("orgshrname"),
            "modules": json.dumps(form_data.get("modules")),  # ✅ Convert array to string
            "custom_modules": form_data.get("custommodules"),
        }

        logger.info(f"Executing Query: {query} with params {params}")  # ✅ Log SQL query execution

        db.execute(query, params)  # ✅ Execute query with parameters
        db.commit()  # ✅ Commit transaction

        logger.info("✅ Form submitted successfully!")  # ✅ Log success
        return {"message": "Form submitted successfully!"}

    except Exception as e:
        db.rollback()  # ✅ Rollback in case of an error
        logger.error(f"🚨 Database Error: {e}")  # ✅ Log error
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")
    
    
    
    
@router.post("/savecontactform")
def submit_contact_form(form_data: ContactFormSchema, db: Session = Depends(get_db)):
    """
    Receives form submission from frontend and saves it to the database using ORM.
    """
    try:
        # ✅ Convert input to ORM model
        new_contact = ConOrgMaster(
            con_org_name=form_data.name,
            con_org_address=form_data.address,
            con_org_pincode=form_data.pincode,
            con_org_state_id=form_data.state,
            con_org_country_id=form_data.country,
            con_org_email_id=form_data.email,
            con_org_mobile=form_data.mobile,
            con_org_contact_person=form_data.contactPerson,
            con_org_shortname=form_data.orgshrname,
            con_org_remarks=form_data.message,
            active=1,
            con_org_master_status=1,
            con_modules_selected=form_data.modules,  # ✅ Store as JSON
            custom_modules=form_data.custommodules,
        )

        db.add(new_contact)  # ✅ Add to DB session
        db.commit()  # ✅ Commit changes
        db.refresh(new_contact)  # ✅ Refresh to get the saved record

        logger.info(f"✅ Form submitted successfully: {new_contact.id}")
        return {"message": "Form submitted successfully!", "id": new_contact.id}

    except Exception as e:
        db.rollback()  # ✅ Rollback in case of an error
        logger.error(f"🚨 Database Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")