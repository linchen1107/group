from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, session, render_template_string, Response
from flask_cors import CORS
import io, csv
from openpyxl import Workbook
import json
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
IDEAL_GROUP_SIZE = 5   # 理想組別人數
MIN_GROUP_SIZE = 4     # 最低組別人數（必須至少 4 人）
MAX_GROUP_SIZE = 5     # 最大組別人數（可達 5 人；若餘數較多時可考慮加至 6 人，但此處設定為 5）

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
    """
    匯出整個班的關係矩陣，若只有單向評分 5 分則另一方預設 3 分 (總和=8)。
    """
    students = get_all_students()
    students_sorted = sorted(students, key=lambda s: s["id"])
    student_ids = [s["id"] for s in students_sorted]
    student_names = [s["name"] for s in students_sorted]
    n = len(student_ids)

    # 收集單向評分，若無評分預設 3 分
    evaluations_grouped = get_all_evaluations_grouped()
    single_map = {}
    for evaluator_id, eval_list in evaluations_grouped.items():
        for record in eval_list:
            single_map[(evaluator_id, record["evaluated_id"])] = record["rating"]

    # 建立 pair_sum
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
    """
    根據班級總人數 N 決定基本組別大小 T。
    """
    if N < 50:
        return 3
    elif N < 80:
        return 4
    elif N < 120:
        return 5
    else:
        return 6

def compute_grouping(anchor_id=None):
    """
    根據全班學生數與評分結果進行分組：
      1. 取得所有學生並依學號排序，根據班級總人數 N 決定基本組別大小 T。
      2. 將前 k = floor(N/T)*T 人依序均分成 k 組，每組 T 人。
      3. 將剩餘 R = N mod T 人，依據與各組平均互評分（synergy）分配到該組（最多 T+1 人）。
      4. 最終調整：若有組別人數不足 MIN_GROUP_SIZE，則嘗試將這些學生搬移到其他組或合併。
      5. 回傳分組結果，每組以 {id, name} 表示。
    """
    students = get_all_students()
    if not students:
        return []
    students_sorted = sorted(students, key=lambda s: s["id"])
    N = len(students_sorted)
    T = determine_target_size(N)
    student_ids = [s["id"] for s in students_sorted]
    student_map = {s["id"]: s["name"] for s in students_sorted}

    # 建立互惠矩陣 M，若無評分則預設 3 分
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

    # 初始均分：將前 k*T 人依序分成 k 組，每組 T 人
    k = N // T
    r = N % T
    groups = []
    for i in range(k):
        group = student_ids[i*T:(i+1)*T]
        groups.append(group)

    # 分配剩餘 R 人，依據與各組的平均互評分分配（只分配到未滿 T+1 的組）
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

    # 最終調整：若有組別人數不足 MIN_GROUP_SIZE，則嘗試搬移學生
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

    # 若仍有組別不足 MIN_GROUP_SIZE，則合併所有不足組
    small_groups = [g for g in groups if len(g) < MIN_GROUP_SIZE]
    if small_groups:
        merged = []
        normal = [g for g in groups if len(g) >= MIN_GROUP_SIZE]
        for g in small_groups:
            merged.extend(g)
        normal.append(merged)
        groups = normal

    # 局部調整：嘗試將某些學生移動到其他組以提升整體 synergy
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

    result = []
    for group in groups:
        result.append([{"id": sid, "name": student_map[sid]} for sid in group])
    return result

@app.route('/auto_grouping', methods=['GET'])
def auto_grouping_route():
    anchor_id = request.args.get("anchor_id")
    groups = compute_grouping(anchor_id)
    return jsonify({"groups": groups})

# ---------------- 後台管理員登入與匯出分組結果 ----------------
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

@app.route('/grouping_result')
def grouping_result():
    return "前端顯示分組結果的頁面（可自行擴充）"

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
