from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, session, render_template_string, Response
from flask_cors import CORS
import io, csv
from openpyxl import Workbook
import json
import math
from db import (
    get_all_students,
    add_evaluation,
    get_evaluations_by_evaluator,
    delete_evaluations_by_evaluator,
    get_all_evaluations_grouped,
    init_settings_table,
    is_form_open,
    set_form_open
)

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # 請自行設定安全的 secret key
CORS(app)

# 分組參數
IDEAL_GROUP_SIZE = 5
MIN_GROUP_SIZE = 4
MAX_GROUP_SIZE = 5

# ---------------- 表單狀態功能 ----------------
init_settings_table()

@app.route('/')
def index():
    students = get_all_students()
    return render_template('index.html', students=json.dumps(students))

@app.route('/close_form', methods=['POST'])
def close_form():
    set_form_open(False)
    return jsonify({"status": "OK", "message": "表單已關閉"})

@app.route('/open_form', methods=['POST'])
def open_form():
    set_form_open(True)
    return jsonify({"status": "OK", "message": "表單已開啟"})

@app.route('/api_form_status', methods=['GET'])
def api_form_status():
    return jsonify({"isOpen": is_form_open()})

@app.route('/submit_evaluation', methods=['POST'])
def submit_evaluation():
    if not is_form_open():
        return jsonify({"error": "表單已關閉，無法提交評分"}), 403

    data = request.get_json()
    if not data or "evaluator" not in data or "evaluations" not in data:
        return jsonify({"error": "資料格式錯誤"}), 400

    evaluator = data["evaluator"]
    evaluator_id = evaluator.get("id")
    if not evaluator_id:
        return jsonify({"error": "缺少 evaluator id"}), 400

    evaluations = data["evaluations"]
    delete_evaluations_by_evaluator(evaluator_id)
    for item in evaluations:
        add_evaluation(evaluator_id, item.get("id"), item.get("name"), int(item.get("rating", 3)))
    return jsonify({"status": "OK", "message": "評分資料已儲存"})

@app.route('/export_relationship_matrix', methods=['GET'])
def export_relationship_matrix():
    students = get_all_students()
    students_sorted = sorted(students, key=lambda s: s["id"])
    student_ids = [s["id"] for s in students_sorted]
    student_names = [s["name"] for s in students_sorted]
    n = len(student_ids)

    evaluations_grouped = get_all_evaluations_grouped()
    single_map = {}
    for evaluator_id, eval_list in evaluations_grouped.items():
        for record in eval_list:
            single_map[(evaluator_id, record["evaluated_id"])] = record["rating"]

    pair_sum = {}
    for i in student_ids:
        for j in student_ids:
            if i == j:
                continue
            r1 = single_map.get((i, j), 3)
            r2 = single_map.get((j, i), 3)
            key = frozenset({i, j})
            pair_sum[key] = r1 + r2

    wb = Workbook()
    ws = wb.active
    ws.title = "Relationship Matrix"
    header = [""] + student_names
    ws.append(header)
    for i in range(n):
        row_data = [student_names[i]]
        for j in range(n):
            if i == j:
                row_data.append(0)
            else:
                key = frozenset({student_ids[i], student_ids[j]})
                row_data.append(pair_sum.get(key, 6))
        ws.append(row_data)
    excel_stream = io.BytesIO()
    wb.save(excel_stream)
    excel_stream.seek(0)
    return send_file(excel_stream, as_attachment=True,
                     download_name="relationship_matrix.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------- 分組演算法 ----------------
def determine_target_size(N):
    if N < 50:
        return 3
    elif N < 80:
        return 4
    elif N < 120:
        return 5
    else:
        return 6

def force_no_small_groups(groups, student_map, min_size=4, max_size=5):
    """
    將原先的分組結果（groups 為各組的 student id 列表）重新分配，
    保證每組人數介於 min_size 與 max_size 之間。
    
    邏輯：
      1. 將所有組員平坦化到一個列表 all_members。
      2. 依照最大組人數計算所需組數 g = ceil(N / max_size)，若 g 組無法滿足每組至少 min_size 人，則增加組數。
      3. 每組先分配 min_size 人，剩餘 extra 人依序補 1 人，使每組人數介於 min_size 與 min_size+1（即 4 或 5）。
      4. 最後將 student id 轉換為 {id, name} 格式回傳。
    """
    # 平坦化所有組員
    all_members = []
    for group in groups:
        all_members.extend(group)
    N = len(all_members)
    
    # 計算初步需要的組數，並確保每組至少 min_size 人
    g = math.ceil(N / max_size)
    if min_size * g > N:
        g += 1
    
    # 每組預設分配 min_size 人，多餘的人依序各組加 1
    extra = N - min_size * g
    new_groups = []
    index = 0
    for i in range(g):
        group_size = min_size
        if extra > 0:
            group_size += 1
            extra -= 1
        new_groups.append(all_members[index:index + group_size])
        index += group_size

    # 將 student id 轉換成包含 id 與 name 的格式
    final_result = []
    for group in new_groups:
        final_result.append([{"id": sid, "name": student_map[sid]} for sid in group])
    return final_result

def compute_grouping(anchor_id=None):
    students = get_all_students()
    if not students:
        return []
    students_sorted = sorted(students, key=lambda s: s["id"])
    N = len(students_sorted)
    T = determine_target_size(N)
    student_ids = [s["id"] for s in students_sorted]
    student_map = {s["id"]: s["name"] for s in students_sorted}

    evaluations_grouped = get_all_evaluations_grouped()
    single_map = {}
    for evaluator_id, eval_list in evaluations_grouped.items():
        for record in eval_list:
            single_map[(evaluator_id, record["evaluated_id"])] = record["rating"]

    M = {}
    for i in student_ids:
        M[i] = {}
        for j in student_ids:
            if i == j:
                M[i][j] = 0
            else:
                r1 = single_map.get((i, j), 3)
                r2 = single_map.get((j, i), 3)
                M[i][j] = r1 + r2

    k = N // T
    r = N % T
    groups = []
    for i in range(k):
        group = student_ids[i*T:(i+1)*T]
        groups.append(group)

    leftover = student_ids[k*T:]
    for sid in leftover:
        best_gid = None
        best_avg = -1
        for idx, group in enumerate(groups):
            if len(group) < T + 1:
                avg = sum(M[sid][member] for member in group) / len(group)
                if avg > best_avg:
                    best_avg = avg
                    best_gid = idx
        if best_gid is not None:
            groups[best_gid].append(sid)
        else:
            groups.append([sid])

    max_adjust = 50
    adjust_iter = 0
    changed = True
    while changed and adjust_iter < max_adjust:
        adjust_iter += 1
        changed = False
        for idx, group in enumerate(groups):
            if len(group) < MIN_GROUP_SIZE:
                for sid in group[:]:
                    best_gid = None
                    best_syn = -1
                    for jdx, other_group in enumerate(groups):
                        if jdx == idx or len(other_group) >= T + 1:
                            continue
                        syn = sum(M[sid][m] for m in other_group)
                        if syn > best_syn:
                            best_syn = syn
                            best_gid = jdx
                    if best_gid is not None:
                        group.remove(sid)
                        groups[best_gid].append(sid)
                        changed = True
        groups = [g for g in groups if g]

    small_groups = [g for g in groups if len(g) < MIN_GROUP_SIZE]
    if small_groups:
        merged = []
        normal = [g for g in groups if len(g) >= MIN_GROUP_SIZE]
        for g in small_groups:
            merged.extend(g)
        normal.append(merged)
        groups = normal

    max_local = 50
    local_iter = 0
    changed = True
    while changed and local_iter < max_local:
        local_iter += 1
        changed = False
        for i in range(len(groups)):
            for sid in groups[i][:]:
                cur_syn = sum(M[sid][m] for m in groups[i])
                best_target = None
                best_gain = 0
                for j in range(len(groups)):
                    if i == j or len(groups[j]) >= T + 1:
                        continue
                    new_syn = sum(M[sid][m] for m in groups[j])
                    gain = new_syn - cur_syn
                    if gain > best_gain:
                        best_gain = gain
                        best_target = j
                if best_target is not None and best_gain > 0:
                    groups[i].remove(sid)
                    groups[best_target].append(sid)
                    changed = True
        groups = [g for g in groups if g]

    # 在最終階段強制確保沒有小組，重新分配成每組 4~5 人
    final_groups = force_no_small_groups(groups, student_map, min_size=4, max_size=5)
    return final_groups

@app.route('/auto_grouping', methods=['GET'])
def auto_grouping_route():
    anchor_id = request.args.get("anchor_id")
    groups = compute_grouping(anchor_id)
    return jsonify({"groups": groups})

# ---------------- 後台管理員登入與相關功能 ----------------
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "11111" and password == "00000":
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "帳號或密碼錯誤"
            return render_template_string('''
                <h2>管理員登入</h2>
                <p style="color:red;">{{ error }}</p>
                <form method="post">
                    帳號: <input type="text" name="username"><br>
                    密碼: <input type="password" name="password"><br>
                    <input type="submit" value="登入">
                </form>
            ''', error=error)
    return render_template_string('''
        <h2>管理員登入</h2>
        <form method="post">
            帳號: <input type="text" name="username"><br>
            密碼: <input type="password" name="password"><br>
            <input type="submit" value="登入">
        </form>
    ''')

@app.route('/admin')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template_string('''
        <h2>管理員後台</h2>
        <p><a href="{{ url_for('admin_export_grouping_csv') }}">匯出分組結果 CSV</a></p>
        <p><a href="{{ url_for('admin_export_grouping') }}">匯出分組結果 Excel</a></p>
        <p><a href="{{ url_for('logout_admin') }}">登出</a></p>
    ''')

@app.route('/logout_admin')
def logout_admin():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/export_grouping_csv', methods=['GET'])
def admin_export_grouping_csv():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    anchor_id = request.args.get("anchor_id")
    groups = compute_grouping(anchor_id)
    groups = [g for g in groups if len(g) > 0]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Group No.", "Members"])
    for i, group in enumerate(groups, start=1):
        member_names = ", ".join([member["name"] for member in group])
        writer.writerow([i, member_names])
    csv_data = output.getvalue()
    output.close()
    
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=grouping_result.csv"}
    )

@app.route('/admin/export_grouping', methods=['GET'])
def admin_export_grouping():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    anchor_id = request.args.get("anchor_id")
    groups = compute_grouping(anchor_id)
    groups = [g for g in groups if len(g) > 0]
    
    max_members = max(len(group) for group in groups)
    wb = Workbook()
    ws = wb.active
    ws.title = "Grouping Result"
    
    header = ["Group No."]
    for i in range(1, max_members+1):
        header.append(f"第{i}位組員")
    ws.append(header)
    
    for i, group in enumerate(groups, start=1):
        row = [i]
        for member in group:
            row.append(member["name"])
        row.extend([""] * (max_members - len(group)))
        ws.append(row)
    
    excel_stream = io.BytesIO()
    wb.save(excel_stream)
    excel_stream.seek(0)
    return send_file(excel_stream, as_attachment=True,
                     download_name="grouping_result.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/management')
def management():
    return render_template('management.html')

# 上傳 Excel 檔案更新班級名單，同時刪除舊的評分資料
@app.route('/admin/upload_classlist', methods=['POST'])
def upload_classlist():
    if not session.get('admin_logged_in'):
        return jsonify({"error": "未授權的存取"}), 403

    file = request.files.get('file')
    if not file:
        return jsonify({"error": "沒有上傳檔案"}), 400

    try:
        import pandas as pd
        df = pd.read_excel(file)

        import sqlite3
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        # 刪除學生名單與評分結果（清空 evaluations）
        c.execute("DELETE FROM students")
        c.execute("DELETE FROM evaluations")
        for index, row in df.iterrows():
            class_name = row.get("班級", "").strip()
            student_id = row.get("學號", "").strip()
            name = row.get("姓名", "").strip()
            c.execute("INSERT INTO students (id, name) VALUES (?, ?)", (student_id, name))
        conn.commit()
        conn.close()

        return jsonify({"message": "上傳成功，資料庫已更新，評分結果已清除"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 新增上傳 XML 檔案並更新班級名單，同時刪除舊的評分結果
@app.route('/admin/upload_classlist_xml', methods=['POST'])
def upload_classlist_xml():
    if not session.get('admin_logged_in'):
        return jsonify({"error": "未授權的存取"}), 403

    file = request.files.get('file')
    if not file:
        return jsonify({"error": "沒有上傳檔案"}), 400

    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(file)
        root = tree.getroot()
        # 假設根節點為 <total_user> 且底下包含多個 <user>
        students = []
        for user in root.findall('user'):
            student_id = user.findtext('username', default="").strip()
            name = user.findtext('realname', default="").strip()
            if student_id and name:
                students.append((student_id, name))

        import sqlite3
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        # 刪除學生資料與評分結果
        c.execute("DELETE FROM students")
        c.execute("DELETE FROM evaluations")
        for student in students:
            c.execute("INSERT INTO students (id, name) VALUES (?, ?)", student)
        conn.commit()
        conn.close()

        return jsonify({"message": "XML上傳成功，資料庫已更新，評分結果已清除"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/grouping_result')
def grouping_result():
    return "前端顯示分組結果的頁面（可自行擴充）"

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
