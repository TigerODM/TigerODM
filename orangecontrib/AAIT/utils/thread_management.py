import inspect
import time

from AnyQt.QtCore import QThread, pyqtSignal

# This function allow to put on separate threads of the GUI some executions function, to allow the GUI to still be responsive
# While output is processed. 

''''
# Start progress bar
self.progressBarInit()

# Connect and start thread : main function, progress, result and finish
# --> progress is used in the main function to track progress (with a callback)
# --> result is used to collect the result from main function
# --> finish is just an empty signal to indicate that the thread is finished
# self.thread = thread_management.Thread(embeddings.create_embeddings, self.data, self.model_path)
self.thread = thread_management.Thread(embeddings.create_embeddings, self.data, self.model)
self.thread.progress.connect(self.handle_progress)
self.thread.result.connect(self.handle_result)
self.thread.finish.connect(self.handle_finish)
self.thread.start()
####-----
def handle_progress(self, value):
    self.progressBarSet(value)
def handle_result(self, result):
    try:
        self.Outputs.data.send(result)
    except Exception as e:
        print("An error occurred when sending out_data:", e)
        self.Outputs.data.send(None)
        return
def handle_finish(self):
    print("Embeddings finished")
    self.progressBarFinished()
'''


class Thread(QThread):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    finish = pyqtSignal()

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.setTerminationEnabled(True)
        self.stop = False

    def run(self):
        inputs = inspect.getfullargspec(self.func).args
        final_args = list(self.args)
        final_kwargs = dict(self.kwargs)

        # Ajout des entrées optionnelles si elles sont attendues par la fonction
        if "progress_callback" in inputs:
            final_kwargs["progress_callback"] = self.progress.emit
        if "argself" in inputs:
            final_kwargs["argself"] = self

        result = self.func(*final_args, **final_kwargs)
        self.result.emit(result)
        self.finish.emit()

    def safe_quit(self):
        self.stop = True
        self.wait()

    def berserk_quit(self):
        self.stop = True
        time.sleep(1)
        if not self.isRunning():
            return
        self.terminate()
        self.wait()
