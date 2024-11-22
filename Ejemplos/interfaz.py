import tkinter as tk
from tkinter import ttk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# Función para calcular, graficar y devolver métricas clave
def calcular_y_graficar(parametros):
    import matplotlib.pyplot as plt

    # Cálculos principales
    hs_man = parametros['hs_man']
    tareas = parametros['tareas']
    periodo = int(parametros['periodo'])
    costo_hora_manual = parametros['$_man']
    costo_hora_desarrollo = parametros['$_dev']
    hs_dev = parametros['hs_dev']
    hs_sop = parametros['hs_sop']

    costo_total_man = hs_man * costo_hora_manual * tareas * periodo
    costo_total_dev = hs_dev * costo_hora_desarrollo + hs_sop * periodo * costo_hora_desarrollo
    df = pd.DataFrame({'Mes': range(1, periodo + 1)}).set_index('Mes')

    df['HH_Man'] = tareas * hs_man
    df['$_Man'] = df['HH_Man'] * costo_hora_manual
    df['HH_Sop'] = hs_sop
    df['$_Sop'] = df['HH_Sop'] * costo_hora_desarrollo
    costo_desarrollo_API = hs_dev * costo_hora_desarrollo
    df['$_Man'] = df['$_Man'].cumsum()
    df['$_Aut'] = costo_desarrollo_API + df['$_Sop'].cumsum()
    df['Ahorro'] = df['$_Man'] - df['$_Aut']
    mes_repago = df[df['Ahorro'] > 0].index.min()

    roi = (df['Ahorro'].iloc[-1] / costo_total_man) * 100 if costo_total_man != 0 else 0

    # Gráfico mejorado
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(df.index, df['$_Man'], label='TCO (Manual)', color='#1f77b4', linewidth=2, where='post')
    ax.plot(df.index, df['$_Aut'], label='TCO (Automatización)', color='#2ca02c', linewidth=2, linestyle='--', where='post')
    ax.plot(df.index, df['Ahorro'], label='Ahorro Acumulado ($)', color='#ff7f0e', linestyle='-.', linewidth=2, where='post')

    if mes_repago:
        ax.axvline(x=mes_repago, color='red', linestyle=':', linewidth=2, label=f'Repago: Mes {mes_repago}')
        ax.text(mes_repago, ax.get_ylim()[1]*0.9, f"Mes {mes_repago}", color='red', fontsize=10, ha='center')

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))
    ax.set_title('Evolución de TCO y Ahorro Acumulado', fontsize=16, fontweight='bold')
    ax.set_xlabel('Meses', fontsize=12)
    ax.set_ylabel('Costo ($)', fontsize=12)
    ax.grid(visible=True, linestyle='--', alpha=0.6)
    ax.legend(loc='upper left', fontsize=10, frameon=True, fancybox=True, shadow=True)
    ax.set_facecolor('#f7f7f7')
    fig.patch.set_facecolor('#ffffff')
    plt.tight_layout()

    return fig, roi, mes_repago, costo_total_man, costo_total_dev



# Función para generar resultados y mostrar resumen
def generar_resultados():
    try:
        parametros = {key: float(entry.get()) for key, entry in entradas_parametros.items()}
        fig, roi, mes_repago, costo_total_man, costo_total_dev = calcular_y_graficar(parametros)

        resumen = (
            f"TCO Manual: ${costo_total_man:.2f}\n"
            f"TCO Automático: ${costo_total_dev:.2f}\n"
            f"ROI: {roi:.2f}%\n"
            f"Periodo de Repago: Mes {mes_repago if mes_repago else 'Sin Repago'}"
        )
        resultados_label.config(text=resumen)
        limpiar_frame(frame_grafico)

        canvas = FigureCanvasTkAgg(fig, master=frame_grafico)
        canvas.draw()
        canvas.get_tk_widget().pack(fill='both', expand=True)

    except Exception as e:
        resultados_label.config(text=f"Error: {str(e)}")

# Limpiar widgets del frame
def limpiar_frame(frame):
    for widget in frame.winfo_children():
        widget.destroy()


# Configuración de la interfaz gráfica


root = tk.Tk()
root.title("Calculadora TCO")
root.geometry("800x600")
root.option_add("*Font", "Arial 12")
style = ttk.Style()
style.theme_use("clam")
root.iconbitmap("icon.ico")


# Notebook para pestañas
notebook = ttk.Notebook(root)
notebook.pack(fill='both', expand=True)

# Pestaña de configuración
frame_config = ttk.Frame(notebook)
notebook.add(frame_config, text="Configuración")

# Entradas para los parámetros con valores iniciales
parametros = ['hs_man', 'tareas', 'periodo', '$_man', '$_dev', 'hs_dev', 'hs_sop']
valores_iniciales = {'hs_man': 10, 'tareas': 5, 'periodo': 12, '$_man': 50, '$_dev': 100, 'hs_dev': 200, 'hs_sop': 5}
entradas_parametros = {}

for idx, param in enumerate(parametros):
    label = ttk.Label(frame_config, text=f"{param}:")
    label.grid(row=idx, column=0, padx=10, pady=5, sticky="w")

    entry = ttk.Entry(frame_config)
    entry.grid(row=idx, column=1, padx=10, pady=5, sticky="w")
    entry.insert(0, valores_iniciales[param])
    entradas_parametros[param] = entry

# Pestaña de resultados
frame_resultados = ttk.Frame(notebook)
notebook.add(frame_resultados, text="Resultados")

resultados_label = ttk.Label(frame_resultados, text="", anchor="w", justify="left")
resultados_label.pack(pady=10, padx=10, fill='x')

frame_grafico = ttk.Frame(frame_resultados)
frame_grafico.pack(fill='both', expand=True)

# Botones para generar resultados y salir
frame_botones = ttk.Frame(root)
frame_botones.pack(fill='x', padx=10, pady=10)

btn_generar = ttk.Button(frame_botones, text="Generar Resultados", command=generar_resultados)
btn_generar.pack(side="left", padx=5)

btn_salir = ttk.Button(frame_botones, text="Salir", command=root.quit)
btn_salir.pack(side="right", padx=5)

root.mainloop()
