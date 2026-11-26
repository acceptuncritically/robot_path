"""
其实这个文件没有必要可以直接在logger_setup.py中实现向上寻找root目录
但是为了以后其他地方用到，先简单解耦一点
"""
import os
def get_project_root()->str:
    """
    获取工程所在的目录
    :return: 字符串
    """
    #当前文件的绝对路径
    current_file=os.path.abspath(__file__)
    #获取工程的根目录,先获得所在文件夹的路径
    current_dir=os.path.dirname(current_file)
    #获取工程的根目录
    current_root=os.path.dirname(current_dir)
    return current_root
def get_abs_path(relative_path:str)->str:
    """
    获取绝对路径
    :param relative_path: 相对路径
    :return: 绝对路径
    """
    current_root=get_project_root()
    return os.path.join(current_root,relative_path)