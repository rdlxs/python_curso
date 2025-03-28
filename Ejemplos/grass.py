import os
import subprocess
import urllib.request
import re

# Configuración
APP_KEYWORD = "Grass"  # Palabra clave del paquete a desinstalar
PROCESS_NAME = "grass"  # Nombre del proceso a cerrar
ftp_url = "ftp://root:manager01@10.254.125.162/Repositorio/img_routers/Grass_5.2.2_amd64.deb"
output_file = "/tmp/Grass_5.2.2_amd64.deb"

def get_installed_package(keyword):
    """Busca el nombre exacto del paquete que coincide con la palabra clave"""
    try:
        result = subprocess.run(["dpkg", "-l"], capture_output=True, text=True, check=True)
        for line in result.stdout.split("\n"):
            if keyword in line:
                parts = line.split()
                if len(parts) > 1:
                    return parts[1]  # Retorna el nombre exacto del paquete
    except subprocess.CalledProcessError as e:
        print(f"Error buscando el paquete: {e}")
    return None

def is_process_running(process_name):
    """Verifica si el proceso está en ejecución"""
    try:
        result = subprocess.run(["pgrep", "-x", process_name], capture_output=True, text=True)
        return result.returncode == 0  # Retorna True si el proceso está corriendo
    except Exception as e:
        print(f"Error verificando el proceso: {e}")
        return False

def stop_process(process_name):
    """Cierra el proceso si está en ejecución"""
    if is_process_running(process_name):
        print(f"Deteniendo {process_name}...")
        try:
            subprocess.run(f"pkill {process_name}", shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error al detener el proceso {process_name}: {e}")
    else:
        print(f"{process_name} no está en ejecución.")

def uninstall_app(keyword):
    """Desinstala una aplicación basada en una palabra clave"""
    package_name = get_installed_package(keyword)
    if package_name:
        print(f"Desinstalando {package_name}...")
        try:
            subprocess.run(f"sudo apt remove -y {package_name} && sudo apt autoremove -y", shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error desinstalando {package_name}: {e}")
    else:
        print(f"No se encontró ningún paquete que contenga '{keyword}'.")

def download_installer(ftp_url, output_file):
    """Descarga el archivo .deb desde un servidor FTP"""
    try:
        # Extraer solo la parte del host y la ruta, omitiendo el usuario y la contraseña
        clean_url = re.sub(r'ftp://([^@]+)@', 'ftp://', ftp_url)  # Elimina usuario y contraseña
        print(f"Descargando {clean_url} ...")
        
        urllib.request.urlretrieve(ftp_url, output_file)
        print(f"✅ Archivo descargado correctamente en {output_file}")
    except Exception as e:
        print(f"❌ Error descargando el archivo: {e}")

def install_deb(deb_path):
    """Instala el paquete .deb y maneja los errores detalladamente"""
    print(f"Instalando {deb_path}...")
    try:
        # Intentamos instalar el paquete .deb con dpkg
        result = subprocess.run(f"sudo dpkg -i {deb_path}", shell=True, capture_output=True, text=True)
        # Si dpkg no tuvo éxito, imprimimos el error
        if result.returncode != 0:
            print(f"❌ Error al instalar el paquete .deb con dpkg: {result.stderr}")
            print(f"Salida estándar: {result.stdout}")
            # Ahora intentamos corregir las dependencias
            print("❗ Intentando reparar dependencias con apt...")
            repair_result = subprocess.run("sudo apt -f install -y", shell=True, capture_output=True, text=True)
            if repair_result.returncode != 0:
                print(f"❌ Error reparando dependencias: {repair_result.stderr}")
                print(f"Salida estándar de apt: {repair_result.stdout}")
            else:
                print("✅ Dependencias reparadas exitosamente.")
        else:
            print("✅ Instalación completada exitosamente con dpkg.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error ejecutando el comando dpkg: {e.stderr}")

def verify_installation(keyword):
    """Verifica si la aplicación está instalada correctamente"""
    package_name = get_installed_package(keyword)
    if package_name:
        print(f"✅ {package_name} se instaló correctamente.")
    else:
        print(f"❌ La instalación de '{keyword}' falló.")

if __name__ == "__main__":
    stop_process(PROCESS_NAME)
    uninstall_app(APP_KEYWORD)
    download_installer(ftp_url, output_file)
    install_deb(output_file)
    verify_installation(APP_KEYWORD)
