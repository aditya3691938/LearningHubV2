import pandas as pd
import io

def parse_assessment_csv(file_stream, filename=None):
    """
    Parses assessment CSV or Excel file with columns:
    Serial Number, Question, Option 1 (or Option1), Option 2 (or Option 2), Option 3 (or Option 3), Option 4 (or Option 4), Option 5 (or Option 5) (Optional), Correct Option
    Returns tuple: (questions_list, errors_list)
    """
    questions = []
    errors = []

    try:
        # Determine whether to read CSV or Excel
        if filename and (str(filename).lower().endswith('.xlsx') or str(filename).lower().endswith('.xls')):
            df = pd.read_excel(file_stream)
        else:
            try:
                df = pd.read_csv(file_stream)
            except Exception:
                if hasattr(file_stream, 'seek'):
                    file_stream.seek(0)
                df = pd.read_excel(file_stream)
        
        # Clean column names (strip whitespace)
        df.columns = [str(c).strip() for c in df.columns]

        # Standardize column headers (map "Option 1" to "Option1", "Option 2" to "Option2", etc.)
        col_mapping = {}
        for col in df.columns:
            cleaned = col.replace(' ', '').replace('_', '').lower()
            if cleaned in ['option1', 'opt1']:
                col_mapping[col] = 'Option1'
            elif cleaned in ['option2', 'opt2']:
                col_mapping[col] = 'Option2'
            elif cleaned in ['option3', 'opt3']:
                col_mapping[col] = 'Option3'
            elif cleaned in ['option4', 'opt4']:
                col_mapping[col] = 'Option4'
            elif cleaned in ['option5', 'opt5']:
                col_mapping[col] = 'Option5'
            elif cleaned in ['serialnumber', 'slno', 'sno', 'sn', 'srno']:
                col_mapping[col] = 'Serial Number'
            elif cleaned in ['correctoption', 'answer', 'correctanswer', 'correct']:
                col_mapping[col] = 'Correct Option'
            elif cleaned in ['question', 'q']:
                col_mapping[col] = 'Question'

        if col_mapping:
            df = df.rename(columns=col_mapping)

        required_cols = ['Question', 'Option1', 'Option2', 'Option3', 'Option4', 'Correct Option']
        
        # Check if required columns exist or map by position if 7 columns
        if len(df.columns) >= 7 and not all(c in df.columns for c in required_cols):
            # Positional mapping (without Option 5)
            df.columns = ['Serial Number', 'Question', 'Option1', 'Option2', 'Option3', 'Option4', 'Correct Option'] + list(df.columns[7:])

        for idx, row in df.iterrows():
            row_num = idx + 1
            question_text = str(row.get('Question', '')).strip()
            opt1 = str(row.get('Option1', '')).strip()
            opt2 = str(row.get('Option2', '')).strip()
            opt3 = str(row.get('Option3', '')).strip()
            opt4 = str(row.get('Option4', '')).strip()
            opt5 = str(row.get('Option5', '')).strip()
            if opt5.lower() == 'nan':
                opt5 = ''
            correct = str(row.get('Correct Option', '')).strip()

            if not question_text or question_text.lower() == 'nan':
                errors.append(f"Row {row_num}: Question is empty.")
                continue

            if not opt1 or not opt2 or not opt3 or not opt4 or any(x.lower() == 'nan' for x in [opt1, opt2, opt3, opt4]):
                errors.append(f"Row {row_num}: All 4 options are required.")
                continue

            if not correct or correct.lower() == 'nan':
                errors.append(f"Row {row_num}: Correct Option is empty.")
                continue

            # Normalize correct option (e.g., 'Option 1' -> 'Option1', '1' -> 'Option1', etc.)
            correct_clean = correct.replace(' ', '').replace('_', '')
            if correct_clean.lower() in ['1', 'option1', 'opt1', 'a']:
                correct = 'Option1'
            elif correct_clean.lower() in ['2', 'option2', 'opt2', 'b']:
                correct = 'Option2'
            elif correct_clean.lower() in ['3', 'option3', 'opt3', 'c']:
                correct = 'Option3'
            elif correct_clean.lower() in ['4', 'option4', 'opt4', 'd']:
                correct = 'Option4'
            elif correct_clean.lower() in ['5', 'option5', 'opt5', 'e']:
                correct = 'Option5'

            serial_num = int(row.get('Serial Number', row_num)) if str(row.get('Serial Number', '')).isdigit() else row_num

            questions.append({
                'serial_number': serial_num,
                'question': question_text,
                'option1': opt1,
                'option2': opt2,
                'option3': opt3,
                'option4': opt4,
                'option5': opt5 if opt5 else None,
                'correct_option': correct
            })

    except Exception as e:
        errors.append(f"Failed to read file: {str(e)}")

    return questions, errors


def evaluate_assessment(questions, user_answers, pass_percentage=80.0):
    """
    Evaluates user answers dictionary {question_id: selected_option}.
    Returns (score_percentage, passed, total_questions, correct_count)
    """
    if not questions:
        return 100.0, True, 0, 0

    correct_count = 0
    total = len(questions)

    for q in questions:
        user_ans = str(user_answers.get(str(q.id)) or user_answers.get(q.id, '')).strip().lower()
        user_ans_clean = user_ans.replace(' ', '').replace('_', '')

        target = str(q.correct_option or '').strip().lower()
        target_clean = target.replace(' ', '').replace('_', '')

        # 1. Exact or normalized option key match ('option1' == 'option1', 'option1' == '1')
        if user_ans_clean == target_clean or f"option{user_ans_clean}" == target_clean or user_ans_clean == f"option{target_clean}":
            correct_count += 1
        else:
            # 2. Map target_clean to option field (e.g. 'option1') and check matching
            opt_key = None
            if target_clean in ['option1', 'opt1', '1', 'a']:
                opt_key = 'option1'
            elif target_clean in ['option2', 'opt2', '2', 'b']:
                opt_key = 'option2'
            elif target_clean in ['option3', 'opt3', '3', 'c']:
                opt_key = 'option3'
            elif target_clean in ['option4', 'opt4', '4', 'd']:
                opt_key = 'option4'
            elif target_clean in ['option5', 'opt5', '5', 'e']:
                opt_key = 'option5'

            if opt_key:
                opt_val = str(getattr(q, opt_key, '') or '').strip().lower()
                opt_val_clean = opt_val.replace(' ', '').replace('_', '')
                if user_ans_clean == opt_key or user_ans_clean == opt_val_clean or user_ans == opt_val:
                    correct_count += 1
            else:
                # 3. Check if target was option text matching user answer
                matched = False
                for opt_attr in ['option1', 'option2', 'option3', 'option4', 'option5']:
                    opt_val = str(getattr(q, opt_attr, '') or '').strip().lower()
                    if target == opt_val and (user_ans_clean == opt_attr or user_ans == opt_val):
                        correct_count += 1
                        matched = True
                        break

    score_percentage = round((correct_count / total) * 100.0, 2)
    passed = score_percentage >= float(pass_percentage)

    return score_percentage, passed, total, correct_count
