import subprocess
import sys
import os
import psutil
import tempfile
import time
import shlex

def open_hide_terminal(command, with_qt=True, env=None):
    """
    Ouvre un nouveau terminal indépendant et exécute la commande spécifiée.
    attention command est une liste
    :param command: La liste de commande à exécuter.
    :param with_qt: Désactive l'affichage si False (utile pour les applications Qt sans affichage).
    :param hide_terminal: Masque la fenêtre du terminal si True.
    :return: Le PID du processus du terminal ouvert.
    """
    hide_terminal = True
    if env is None:
        env = dict(os.environ)
    if not with_qt:
        if sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
            print("Warning: 'offscreen' mode may not be fully supported on Mac.")
        else:
            env['QT_QPA_PLATFORM'] = 'offscreen'
    if not with_qt:
        env['QT_QPA_PLATFORM'] = 'offscreen'

    process = None
    if not isinstance(command, list):
        raise RuntimeError("error command need to be a list")
    if len(command)==0:
        raise RuntimeError("error command need to be a list with elements")


    if sys.platform.startswith("win"):
        process = subprocess.Popen(
            command,
            env=env,
            shell=False,
            creationflags=(
                    subprocess.CREATE_NO_WINDOW |
                    subprocess.CREATE_NEW_PROCESS_GROUP
            ),
        )

        # startupinfo = subprocess.STARTUPINFO()
        # startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        #
        # # Code 0 = SW_HIDE (cacher la console), mais ne gêne pas la GUI (ex : Qt)
        # startupinfo.wShowWindow = 0
        # creationflags = 0
        #
        # process = subprocess.Popen(
        #     command,
        #     env=env,
        #     startupinfo=startupinfo,
        #     creationflags=creationflags
        # )
    elif sys.platform.startswith("linux"):
        command_chaine = ' '.join(command)
        if hide_terminal:
            process = subprocess.Popen(["bash", "-c", command_chaine], env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        else:
            try:
                process = subprocess.Popen(["gnome-terminal", "--", "bash", "-c", command_chaine + "; exec bash"], env=env)
            except FileNotFoundError:
                process = subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-c", command_chaine + "; exec bash"],
                                           env=env)


    elif sys.platform.startswith("Darwin") or sys.platform.startswith("darwin") :
        command_chaine = ' '.join(command)
        if hide_terminal:
            if with_qt == False:
                command_chaine = "QT_QPA_PLATFORM=offscreen " + command_chaine
                # Lancer bash sans ouvrir un terminal visible
                process = subprocess.Popen(
                    ["/bin/bash", "-c", command_chaine],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Lancer bash sans ouvrir un terminal visible
                process = subprocess.Popen(
                    ["/bin/bash", "-c", command_chaine],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        else:
            if with_qt==False:
                command = "QT_QPA_PLATFORM=offscreen " + command_chaine
                # Sinon ouvrir Terminal.app
                process = subprocess.Popen(["osascript", "-e", f'tell app "Terminal" to do script \"{command_chaine}\"'])
            else:
                # Sinon ouvrir Terminal.app
                process = subprocess.Popen(["osascript", "-e", f'tell app "Terminal" to do script \"{command_chaine}\"'])
    if process:
        return process.pid
    else:
        raise RuntimeError("Impossible d'ouvrir le terminal.")


def open_terminal(command, with_qt=True, env=None):
    """
    attention command est une liste
    Ouvre un nouveau terminal indépendant et exécute la commande spécifiée.
    :param command: La liste de commande à exécuter.
    :param with_qt: Désactive l'affichage si False (utile pour les applications Qt sans affichage).
    :return: Le PID du processus du terminal ouvert.
    """
    if env is None:
        env = dict(os.environ)
    if not with_qt:
        if sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
            print("Warning: 'offscreen' mode may not be fully supported on Mac.")
        else:
            env['QT_QPA_PLATFORM'] = 'offscreen'
    if not with_qt:
        env['QT_QPA_PLATFORM'] = 'offscreen'
    process = None
    if not isinstance(command, list):
        raise RuntimeError("error command need to be a list")
    if len(command)==0:
        raise RuntimeError("error command need to be a list with elements")



    if sys.platform.startswith("win"):
        # j insere cmd /k command
        # command.insert(0,"/k")
        # command.insert(0, "cmd.exe")
        # process = subprocess.Popen(command, env=env,creationflags=subprocess.CREATE_NEW_CONSOLE)
        process = subprocess.Popen(
            command,
            env=env,
            creationflags=(
                    subprocess.CREATE_NEW_CONSOLE |
                    subprocess.CREATE_NEW_PROCESS_GROUP
            )
        )

        if process:
            return process.pid
        else:
            raise RuntimeError("Impossible d'ouvrir le terminal.")
    elif sys.platform.startswith("linux"):
        command_chaine = ' '.join(command)
        try:
            process = subprocess.Popen(["gnome-terminal", "--", "bash", "-c", command_chaine + "; exec bash"], env=env)
        except FileNotFoundError:
            process = subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-c", command_chaine + "; exec bash"], env=env)
        if process:
            return process.pid
        else:
            raise RuntimeError("Impossible d'ouvrir le terminal.")

    elif sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
        # macOS: on écrit $$ (PID du shell) dans un fichier, puis on remplace le shell avec exec
        pidfile = tempfile.NamedTemporaryFile(delete=False)
        pidfile_path = pidfile.name
        pidfile.close()

        command_chaine = ' '.join(shlex.quote(c) for c in command)
        if not with_qt:
            command_chaine = f"QT_QPA_PLATFORM=offscreen {command_chaine}"

        # Important: "exec" pour que le shell soit remplacé par le vrai process
        wrapped_command = f'echo $$ > {pidfile_path}; exec {command_chaine}'

        applescript = f'''
                    tell application "Terminal" 
                        do script "bash -c \\"{wrapped_command}\\"" 
                    end tell'''
        osa_proc = subprocess.Popen(["osascript", "-e", applescript])
        osa_proc.wait()  # évite les zombies

        # Attente active pour que le PID soit écrit
        pid = None
        for _ in range(30):  # max 3 secondes
            try:
                with open(pidfile_path, "r") as f:
                    pid_str = f.read().strip()
                    if pid_str:
                        pid = int(pid_str)
                        break
            except FileNotFoundError:
                pass
            time.sleep(0.1)

        os.unlink(pidfile_path)  # Nettoyage
        if pid:
            return pid
        else:
            raise RuntimeError("Impossible de récupérer le PID du processus lancé dans Terminal.")
    else:
        raise RuntimeError("Unsupported platform.")


def execute_command(command: str, hidden: bool = True,env=None):
    """
    Exécute une commande dans un terminal caché ou visible avec option d'attente.

    :param command: La ligne de commande à exécuter
    :param hidden: Exécuter dans un terminal caché si True, visible sinon
    :param wait: Attendre la fin de l'exécution si True, sinon continuer en parallèle
    :return: (code de retour, PID du processus ou None en cas d'échec)
    """
    try:
        startupinfo = None
        creationflags = 0
        shell = False

        # Gestion spécifique pour Windows
        if os.name == "nt":
            if hidden:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NEW_CONSOLE
            else:
                command = f'start cmd.exe /k echo {command} & {command}'
            shell = True  # Nécessaire pour certaines commandes Windows
        if env is None:
            # Détermine la manière de lancer le processus
            process = subprocess.Popen(
                command,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo if os.name == "nt" else None,
                creationflags=creationflags if os.name == "nt" else 0,
            )
        else:
            # Détermine la manière de lancer le processus
            process = subprocess.Popen(
                command,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo if os.name == "nt" else None,
                creationflags=creationflags if os.name == "nt" else 0,
                env=env,
            )



        return 0, process.pid  # Succès avec PID

    except Exception as e:
        print(f"Erreur: {e}", file=sys.stderr)
        return 1, None  # Erreur


def kill_process(pid: int):
    """
    Tue un processus à partir de son PID.
    :param pid: L'identifiant du processus à tuer
    :return: 0 si succès, 1 en cas d'erreur
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True)
        else:
            os.kill(pid, 9)  # Signal SIGKILL
        return 0
    except Exception as e:
        print(f"Erreur lors de la suppression du processus {pid}: {e}", file=sys.stderr)
        return 1

def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            print(f"Tuer enfant PID {child.pid} ({child.name()})")
            child.kill()

        if sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
            # Attendre un peu pour que les enfants meurent proprement
            gone, alive = psutil.wait_procs(children, timeout=3)
            for p in alive:
                print(f"Enfant PID {p.pid} n'a pas terminé, on le force")
                p.kill()

        parent.kill()
        print(f"Processus principal {pid} tué.")

    except psutil.NoSuchProcess:
        print(f"Le processus {pid} n'existe pas.")
    except Exception as e:
        print(f"Erreur lors du kill du process tree : {e}")
