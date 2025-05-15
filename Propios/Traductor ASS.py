import os
from flask import Flask, request, render_template_string, send_file, jsonify
from deep_translator import GoogleTranslator
import threading

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

progress = {'total': 0, 'current': 0, 'done': False, 'filename': ''}

HTML_TEMPLATE = '''
<!doctype html>
<title>Traductor de Subtítulos .ASS</title>
<h2>Subí tu archivo .ASS en ruso y lo traducimos al español latinoamericano</h2>
<form method=post enctype=multipart/form-data>
  <input type=file name=file>
  <input type=submit value='Traducir'>
</form>
<div id="progress"></div>
{% if output_file %}
  <p>✅ Traducción completada. <a href="{{ url_for('download_file', filename=output_file) }}">Descargar subtítulo traducido</a></p>
{% endif %}
<script>
function fetchProgress() {
  fetch('/progress')
    .then(response => response.json())
    .then(data => {
      if (data.done) {
        location.reload();
      } else {
        document.getElementById('progress').innerText = `Progreso: ${data.current}/${data.total}`;
        setTimeout(fetchProgress, 1000);
      }
    });
}
fetchProgress();
</script>
'''

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    output_file = None
    if request.method == 'POST':
        uploaded_file = request.files['file']
        if uploaded_file.filename.endswith('.ass'):
            input_path = os.path.join(UPLOAD_FOLDER, uploaded_file.filename)
            uploaded_file.save(input_path)
            output_filename = uploaded_file.filename.replace('.ass', '_ES.ass')
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            progress['filename'] = output_filename
            progress['done'] = False
            thread = threading.Thread(target=traducir_ass, args=(input_path, output_path))
            thread.start()
    if progress['done']:
        output_file = progress['filename']
    return render_template_string(HTML_TEMPLATE, output_file=output_file)

@app.route('/progress')
def get_progress():
    return jsonify(progress)

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

def traducir_ass(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    dialog_lines = [line for line in lines if line.startswith("Dialogue:")]
    progress['total'] = len(dialog_lines)
    progress['current'] = 0

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
                progress['current'] += 1
            else:
                traducciones.append(line)
        else:
            traducciones.append(line)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(traducciones)

    progress['done'] = True

if __name__ == '__main__':
    app.run(debug=True, port=5000)
