import os
import subprocess
import ftplib
import tempfile
import shutil
import time

PACKAGE_NAME = "grass"
DEB_FILENAME = "Grass_5.5.4_amd64.deb"
FTP_HOST = "ftp://10.254.125.162/Repositorio/img_routers/"
FTP_USER = "root"
FTP_PASS = "manager01"

def is_package_installed(pkg_name):
    result = subprocess.run(["dpkg", "-l", pkg_name], capture_output=True, text=True)
    return pkg_name in result.stdout

def kill_process_if_running(pkg_name):
    result = subprocess.run(["pgrep", "-f", pkg_name], capture_output=True, text=True)
    if result.stdout:
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            print(f"🛑 Matando proceso activo: PID {pid}")
            subprocess.run(["kill", "-9", pid])

def uninstall_package(pkg_name):
    print(f"🧼 Desinstalando {pkg_name} si está presente...")
    subprocess.run(["apt", "remove", "-y", pkg_name], check=False)

def download_deb_from_ftp():
    tmp_dir = tempfile.gettempdir()
    deb_path = os.path.join(tmp_dir, DEB_FILENAME)
    print(f"📡 Conectando a FTP: {FTP_HOST}")
    with ftplib.FTP(FTP_HOST) as ftp:
        ftp.login(FTP_USER, FTP_PASS)
        with open(deb_path, "wb") as f:
            print(f"⬇️  Descargando {DEB_FILENAME} a {deb_path}")
            ftp.retrbinary(f"RETR {DEB_FILENAME}", f.write)
    return deb_path

def fix_tmp_permissions():
    print("🔧 Ajustando permisos de /tmp")
    subprocess.run(["chmod", "1777", "/tmp"], check=True)

def install_deb(deb_path):
    print(f"📦 Instalando {deb_path}")
    subprocess.run(["dpkg", "-i", deb_path], check=False)
    print("🔁 Corrigiendo dependencias si es necesario...")
    subprocess.run(["apt", "-f", "install", "-y"], check=True)

def verify_install(pkg_name):
    print("🔍 Verificando si la instalación fue exitosa...")
    installed = is_package_installed(pkg_name)
    if installed:
        print(f"✅ {pkg_name} instalado correctamente.")
    else:
        print(f"❌ Error: {pkg_name} no está instalado.")

def clean(deb_path):
    if os.path.exists(deb_path):
        os.remove(deb_path)
        print(f"🧹 Eliminado: {deb_path}")

def main():
    try:
        subprocess.run(["apt", "update"], check=True)
        if is_package_installed(PACKAGE_NAME):
            kill_process_if_running(PACKAGE_NAME)
            uninstall_package(PACKAGE_NAME)
        fix_tmp_permissions()
        deb_path = download_deb_from_ftp()
        install_deb(deb_path)
        verify_install(PACKAGE_NAME)
    except Exception as e:
        print(f"💥 Error durante la instalación: {e}")
    finally:
        clean(os.path.join(tempfile.gettempdir(), DEB_FILENAME))

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️ Este script debe ejecutarse como root (sudo).")
    else:
        main()
