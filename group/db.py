import sqlite3

DATABASE = 'database.db'

def get_all_students():
    """
    從 students 資料表讀取所有學生資料，
    回傳格式：[{'id': 學號, 'name': 姓名}, ...]
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, name FROM students")
    rows = c.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1]} for row in rows]

def add_evaluation(evaluator_id, evaluated_id, evaluated_name, rating):
    """
    儲存單筆評分資料到 evaluations 資料表
    如果 evaluations 資料表尚未建立，則先建立之。
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluator_id TEXT NOT NULL,
            evaluated_id TEXT NOT NULL,
            evaluated_name TEXT NOT NULL,
            rating INTEGER NOT NULL
        )
    ''')
    c.execute('''
        INSERT INTO evaluations (evaluator_id, evaluated_id, evaluated_name, rating)
        VALUES (?, ?, ?, ?)
    ''', (evaluator_id, evaluated_id, evaluated_name, rating))
    conn.commit()
    conn.close()

def get_evaluations_by_evaluator(evaluator_id):
    """
    根據評分者（evaluator_id）讀取該次評分的所有資料，
    回傳格式：[{'evaluated_id': ..., 'evaluated_name': ..., 'rating': ...}, ...]
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT evaluated_id, evaluated_name, rating FROM evaluations WHERE evaluator_id=?", (evaluator_id,))
    rows = c.fetchall()
    conn.close()
    return [{"evaluated_id": row[0], "evaluated_name": row[1], "rating": row[2]} for row in rows]

def delete_evaluations_by_evaluator(evaluator_id):
    """
    刪除指定評分者（evaluator_id）之前所有的評分資料，
    以便後續儲存最新的評分結果。
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM evaluations WHERE evaluator_id=?", (evaluator_id,))
    conn.commit()
    conn.close()

def get_all_evaluations_grouped():
    """
    讀取所有評分資料，根據評分者（evaluator_id）分組。
    回傳格式：
    {
      "評分者學號1": [
         {"evaluated_id": ..., "evaluated_name": ..., "rating": ...},
         {...},
         ...
      ],
      "評分者學號2": [
         ...
      ],
      ...
    }
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT evaluator_id, evaluated_id, evaluated_name, rating FROM evaluations ORDER BY evaluator_id")
    rows = c.fetchall()
    conn.close()
    grouped = {}
    for evaluator_id, evaluated_id, evaluated_name, rating in rows:
        if evaluator_id not in grouped:
            grouped[evaluator_id] = []
        grouped[evaluator_id].append({
            "evaluated_id": evaluated_id,
            "evaluated_name": evaluated_name,
            "rating": rating
        })
    return grouped

if __name__ == '__main__':
    # 測試用途：印出依評分者分組的所有評分資料
    grouped_evaluations = get_all_evaluations_grouped()
    # for evaluator, evaluations in grouped_evaluations.items():
    #     print(f"評分者 {evaluator} 的評分結果：")
    #     for eval_item in evaluations:
    #         print(f"  {eval_item['evaluated_name']} ({eval_item['evaluated_id']}) 評分：{eval_item['rating']}")

def init_settings_table():
    """
    若 settings 表不存在，則建立一個簡單的 key-value 表
    並將 form_open 預設為 '1' (open)
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # 檢查是否已存在 form_open
    c.execute("SELECT value FROM settings WHERE key='form_open'")
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO settings (key, value) VALUES ('form_open', '1')")
    conn.commit()
    conn.close()

def is_form_open():
    """
    回傳 True/False 表示表單是否開放
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='form_open'")
    row = c.fetchone()
    conn.close()
    if row and row[0] == '1':
        return True
    return False

def set_form_open(open_flag: bool):
    """
    將表單狀態設定為 open_flag
    True => '1'
    False => '0'
    """
    val = '1' if open_flag else '0'
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE settings SET value=? WHERE key='form_open'", (val,))
    conn.commit()
    conn.close()