import os
import subprocess
import ftplib
import tempfile
import time


DEB_FILENAME = "grass-desktop_7.5.1_amd64.deb"

FTP_HOST = "10.254.125.162"
FTP_DIR = "/Repositorio/img_routers/"
FTP_USER = "root"
FTP_PASS = "manager01"

# Se usa para localizar procesos relacionados con la aplicación.
# La búsqueda no exige que el proceso se llame exactamente "grass".
PROCESS_SEARCH_TERM = "grass"


def run_command(command, check=False):
    """
    Ejecuta un comando del sistema.

    Centralizar subprocess.run evita repetir los mismos parámetros
    en todas las funciones.
    """
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check
    )


def get_package_name_from_deb(deb_path):
    """
    Obtiene el nombre real del paquete definido dentro del archivo .deb.

    Por ejemplo, aunque el archivo se llame:
        grass-desktop_7.4.4_amd64.deb

    El campo Package podría ser:
        grass-desktop
    """
    result = run_command(
        ["dpkg-deb", "--field", deb_path, "Package"],
        check=True
    )

    package_name = result.stdout.strip()

    if not package_name:
        raise RuntimeError(
            f"No se pudo determinar el nombre del paquete desde {deb_path}"
        )

    print(f"📋 Nombre real del paquete: {package_name}")
    return package_name


def is_package_installed(package_name):
    """
    Consulta el estado exacto del paquete mediante dpkg-query.

    La salida esperada para un paquete correctamente instalado es:
        install ok installed
    """
    result = run_command(
        [
            "dpkg-query",
            "-W",
            "-f=${Status}",
            package_name
        ]
    )

    if result.returncode != 0:
        return False

    return result.stdout.strip() == "install ok installed"


def get_excluded_pids():
    """
    Obtiene el PID del script y sus procesos padre.

    Esto evita matar accidentalmente:
    - El propio script.
    - El proceso sudo.
    - La terminal o shell que ejecutó el script.

    Es especialmente importante si el archivo se llama, por ejemplo:
        install_grass.py
    """
    excluded_pids = set()

    current_pid = os.getpid()

    while current_pid > 1:
        excluded_pids.add(current_pid)

        result = run_command(
            ["ps", "-p", str(current_pid), "-o", "ppid="]
        )

        if result.returncode != 0 or not result.stdout.strip():
            break

        try:
            current_pid = int(result.stdout.strip())
        except ValueError:
            break

    return excluded_pids


def find_running_processes(search_term):
    """
    Busca procesos cuyo nombre o línea de comandos contenga search_term.

    No se exige coincidencia exacta. Por ejemplo, buscando 'grass'
    encontrará:

        grass
        grass-desktop
        /opt/Grass/grass
        electron /opt/Grass/resources/app.asar
    """
    result = run_command(
        ["ps", "-eo", "pid=,comm=,args="],
        check=True
    )

    excluded_pids = get_excluded_pids()
    search_term = search_term.casefold()
    matching_processes = []

    for line in result.stdout.splitlines():
        process_data = line.strip().split(maxsplit=2)

        if len(process_data) < 2:
            continue

        try:
            pid = int(process_data[0])
        except ValueError:
            continue

        if pid in excluded_pids:
            continue

        process_name = process_data[1]
        process_args = process_data[2] if len(process_data) == 3 else ""

        searchable_text = f"{process_name} {process_args}".casefold()

        if search_term in searchable_text:
            matching_processes.append(
                {
                    "pid": pid,
                    "name": process_name,
                    "args": process_args
                }
            )

    return matching_processes


def is_process_running(search_term):
    """
    Devuelve True si existe al menos un proceso relacionado.
    """
    return bool(find_running_processes(search_term))


def process_exists(pid):
    """
    Comprueba si un PID sigue existiendo.

    os.kill(pid, 0) no envía una señal real. Solo consulta si el
    proceso existe y si tenemos permisos para acceder a él.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_processes_if_running(search_term):
    """
    Detiene los procesos relacionados con la aplicación.

    Primero utiliza SIGTERM para permitir un cierre ordenado.
    Si el proceso continúa activo, utiliza SIGKILL.
    """
    processes = find_running_processes(search_term)

    if not processes:
        print(
            f"✅ No hay procesos activos que contengan "
            f"'{search_term}' en su nombre o comando."
        )
        return

    print(
        f"🔎 Se encontraron {len(processes)} procesos "
        f"relacionados con '{search_term}'."
    )

    for process in processes:
        pid = process["pid"]
        command = process["args"] or process["name"]

        print(f"🛑 Enviando SIGTERM al PID {pid}: {command}")

        subprocess.run(
            ["kill", "-TERM", str(pid)],
            check=False
        )

    # Se espera brevemente para que los procesos puedan cerrarse
    # correctamente antes de recurrir a SIGKILL.
    time.sleep(2)

    for process in processes:
        pid = process["pid"]

        if process_exists(pid):
            print(
                f"⚠️ El PID {pid} continúa activo. "
                f"Enviando SIGKILL."
            )

            subprocess.run(
                ["kill", "-KILL", str(pid)],
                check=False
            )
        else:
            print(f"✅ PID {pid} detenido correctamente.")


def uninstall_package(package_name):
    """
    Desinstala el paquete utilizando su nombre real.
    """
    print(f"🧼 Desinstalando el paquete {package_name}...")

    result = subprocess.run(
        ["apt", "remove", "-y", package_name],
        check=False
    )

    if result.returncode != 0:
        print(
            f"⚠️ apt no pudo desinstalar correctamente "
            f"el paquete {package_name}."
        )


def download_deb_from_ftp():
    """
    Descarga el archivo .deb en el directorio temporal del sistema.
    """
    tmp_dir = tempfile.gettempdir()
    deb_path = os.path.join(tmp_dir, DEB_FILENAME)

    print(f"📡 Conectando al FTP: {FTP_HOST}")

    with ftplib.FTP(FTP_HOST, timeout=30) as ftp:
        ftp.login(FTP_USER, FTP_PASS)
        ftp.cwd(FTP_DIR)

        print(f"⬇️ Descargando {DEB_FILENAME} a {deb_path}")

        with open(deb_path, "wb") as deb_file:
            ftp.retrbinary(
                f"RETR {DEB_FILENAME}",
                deb_file.write
            )

    return deb_path


def fix_tmp_permissions():
    """
    Establece los permisos estándar del directorio /tmp.

    1777 significa:
    - Todos pueden escribir.
    - Cada usuario solo puede borrar sus propios archivos.
    """
    print("🔧 Ajustando permisos de /tmp")
    subprocess.run(["chmod", "1777", "/tmp"], check=True)


def install_deb(deb_path):
    """
    Instala el paquete y corrige dependencias faltantes.
    """
    print(f"📦 Instalando {deb_path}")

    dpkg_result = subprocess.run(
        ["dpkg", "-i", deb_path],
        check=False
    )

    if dpkg_result.returncode != 0:
        print(
            "⚠️ dpkg informó errores. "
            "Puede tratarse de dependencias pendientes."
        )

    print("🔁 Corrigiendo dependencias si es necesario...")

    subprocess.run(
        ["apt", "-f", "install", "-y"],
        check=True
    )


def verify_install(package_name):
    """
    Comprueba que el paquete haya quedado en estado
    'install ok installed'.
    """
    print("🔍 Verificando la instalación...")

    if is_package_installed(package_name):
        print(f"✅ {package_name} instalado correctamente.")
        return True

    print(f"❌ El paquete {package_name} no quedó instalado.")
    return False


def clean(deb_path):
    """
    Elimina el instalador temporal.
    """
    if deb_path and os.path.exists(deb_path):
        os.remove(deb_path)
        print(f"🧹 Archivo temporal eliminado: {deb_path}")


def main():
    deb_path = None

    try:
        subprocess.run(["apt", "update"], check=True)

        fix_tmp_permissions()

        # Primero se descarga el archivo para poder consultar
        # el nombre real declarado dentro del paquete.
        deb_path = download_deb_from_ftp()

        package_name = get_package_name_from_deb(deb_path)

        package_installed = is_package_installed(package_name)
        process_running = is_process_running(PROCESS_SEARCH_TERM)

        print(f"📦 Paquete instalado: {'sí' if package_installed else 'no'}")
        print(f"▶️ Aplicación ejecutándose: {'sí' if process_running else 'no'}")

        # Los procesos se cierran incluso si dpkg no reconoce el paquete.
        # Esto contempla instalaciones manuales o procesos residuales.
        if process_running:
            kill_processes_if_running(PROCESS_SEARCH_TERM)

        if package_installed:
            uninstall_package(package_name)

            if is_package_installed(package_name):
                raise RuntimeError(
                    f"El paquete {package_name} continúa instalado "
                    f"después de ejecutar apt remove."
                )

            print(f"✅ Paquete anterior {package_name} desinstalado.")

        install_deb(deb_path)

        if not verify_install(package_name):
            raise RuntimeError(
                f"No se pudo instalar correctamente {package_name}"
            )

    except subprocess.CalledProcessError as error:
        command = " ".join(error.cmd) if error.cmd else "desconocido"

        print(
            f"💥 Falló el comando '{command}' "
            f"con código {error.returncode}."
        )

        if error.stderr:
            print(error.stderr.strip())

    except ftplib.all_errors as error:
        print(f"💥 Error durante la descarga FTP: {error}")

    except Exception as error:
        print(f"💥 Error durante la instalación: {error}")

    finally:
        clean(deb_path)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️ Este script debe ejecutarse como root utilizando sudo.")
        raise SystemExit(1)

    main()