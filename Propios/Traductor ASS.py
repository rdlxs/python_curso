import os
import uuid
from flask import Flask, request, render_template_string, send_file, jsonify
from deep_translator import GoogleTranslator
import threading

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

progress_dict = {}

HTML_TEMPLATE = '''
<!doctype html>
<title>Traductor de Subtítulos .ASS</title>
<h2>Subí tus archivos .ASS en ruso y los traducimos al español latinoamericano</h2>
<form method=post enctype=multipart/form-data>
  <input type=file name=files multiple>
  <input type=submit value='Traducir'>
</form>
<div id="progress-container"></div>
<ul id="download-links"></ul>
<script>
function fetchProgress() {
  fetch('/progress')
    .then(response => response.json())
    .then(data => {
      const container = document.getElementById('progress-container');
      const downloads = document.getElementById('download-links');
      container.innerHTML = '';
      downloads.innerHTML = '';
      Object.entries(data).forEach(([task_id, prog]) => {
        const percent = Math.floor((prog.current / prog.total) * 100);
        const bar = `<div style='margin-bottom: 10px;'>
          <strong>${prog.filename}</strong>
          <div style='background: #ddd; width: 100%; height: 20px; border-radius: 5px;'>
            <div style='width: ${percent}%; height: 100%; background: ${prog.done ? "#4CAF50" : "#2196F3"}; border-radius: 5px;'></div>
          </div>
          <small>${prog.current}/${prog.total}</small>
        </div>`;
        container.innerHTML += bar;
        if (prog.done) {
          downloads.innerHTML += `<li><a href='/download/${prog.output_file}'>Descargar: ${prog.output_file}</a></li>`;
        }
      });
      setTimeout(fetchProgress, 1000);
    });
}
fetchProgress();
</script>
'''

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        files = request.files.getlist('files')
        for file in files:
            if file.filename.endswith('.ass'):
                input_filename = str(uuid.uuid4()) + ".ass"
                input_path = os.path.join(UPLOAD_FOLDER, input_filename)
                file.save(input_path)
                output_filename = file.filename.replace('.ass', '_ES.ass')
                output_path = os.path.join(OUTPUT_FOLDER, output_filename)

                task_id = str(uuid.uuid4())
                progress_dict[task_id] = {
                    'total': 1, 'current': 0, 'done': False,
                    'filename': file.filename,
                    'output_file': output_filename
                }

                thread = threading.Thread(target=traducir_ass, args=(input_path, output_path, task_id))
                thread.start()
    return render_template_string(HTML_TEMPLATE)

@app.route('/progress')
def get_progress():
    return jsonify(progress_dict)

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

def traducir_ass(input_file, output_file, task_id):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    dialog_lines = [line for line in lines if line.startswith("Dialogue:")]
    progress_dict[task_id]['total'] = len(dialog_lines)
    progress_dict[task_id]['current'] = 0

    traducciones = []
    for line in lines:
        if line.startswith("Dialogue:"):
            partes = line.strip().split(",", 9)
            if len(partes) == 10:
                texto_original = partes[9]
                texto_limpio = texto_original.replace("{\\an8}", "")
                try:
                    traduccion = GoogleTranslator(source='ru', target='es').translate(texto_limpio)
                except:
                    traduccion = texto_original
                partes[9] = traduccion
                traducciones.append(",".join(partes) + "\n")
                progress_dict[task_id]['current'] += 1
            else:
                traducciones.append(line)
        else:
            traducciones.append(line)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(traducciones)

    progress_dict[task_id]['done'] = True

if __name__ == '__main__':
    app.run(debug=True, port=5000)
