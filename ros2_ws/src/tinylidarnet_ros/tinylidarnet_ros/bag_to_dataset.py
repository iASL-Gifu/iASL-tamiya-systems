"""従来のros2 runコマンド用入口。変換本体はROS非依存。"""

from tinylidarnet.bag_to_dataset import main


if __name__ == '__main__':
    main()
