INSERT_USER = """
    INSERT INTO user_mst (email_id, name, password, active, updated_by_con_user)
    VALUES (%s, %s, %s, 1, 0)
"""

GET_USER_BY_EMAIL = """
    SELECT user_id, email_id, name, password, active
    FROM user_mst
    WHERE email_id = %s AND active = 1
"""
print("Q.INSERT_USER:", {GET_USER_BY_EMAIL})