import pandas as pd
import json

def convert_excel_to_json():
    """
    Reads quiz data from an Excel file, transforms it, and saves it as a JSON file.
    """
    excel_file_path = 'brick_quiz/Neuer_Arzttarif_Frage_Antwort_Spiel.xlsx'
    json_file_path = 'brick_quiz/questions.js'

    try:
        # Read the Excel file
        df = pd.read_excel(excel_file_path)

        expected_columns = ['Stichwort', 'Frage', 'Antwort_1', 'Antwort_2', 'Antwort_3', 'Korrekte_Antwort']
        actual_columns = df.columns.tolist()
        missing_columns = [col for col in expected_columns if col not in actual_columns]

        if missing_columns:
            print(f"Error: The Excel file is missing the following expected columns: {missing_columns}")
            print(f"The columns found in the Excel file are: {actual_columns}")
            return

        questions_data = []

        for index, row in df.iterrows():
            title = str(row['Stichwort'])
            question_text = str(row['Frage'])
            answers = [str(row['Antwort_1']), str(row['Antwort_2']), str(row['Antwort_3'])]
            # Convert 1-indexed correct answer to 0-indexed
            correct_answer_index = int(row['Korrekte_Antwort']) - 1

            question_dict = {
                'title': title,
                'question': question_text,
                'answers': answers,
                'correct_answer_index': correct_answer_index
            }
            questions_data.append(question_dict)
        
        # Convert the list of dictionaries to a JSON string
        json_output = json.dumps(questions_data, indent=4, ensure_ascii=False)
        
        # Save the JSON string to a file as a JS variable assignment
        with open(json_file_path, 'w', encoding='utf-8') as f:
            f.write(f"window.questionsData = {json_output};")
        
        print(f"Successfully converted data from {excel_file_path} to {json_file_path}")
        print(f"Total questions processed: {len(questions_data)}")

    except FileNotFoundError:
        print(f"Error: The file {excel_file_path} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    convert_excel_to_json()
