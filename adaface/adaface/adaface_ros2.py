import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.qos import QoSProfile
from rclpy.qos import QoSHistoryPolicy
from rclpy.qos import QoSDurabilityPolicy
from rclpy.qos import QoSReliabilityPolicy

import message_filters
from cv_bridge import CvBridge

from yolov8_msgs.msg import Detection
from yolov8_msgs.msg import DetectionArray
from sensor_msgs.msg._image import Image

import numpy as np
import sys
import os

sys.path.append(os.path.join(os.path.expanduser("~"), "moiro_ws/src/faceRec_ros2/adaface/adaface/script"))

from adaface.script.adaface  import AdaFace

'''
This Node subscribes datas from ~yolo/tracking_node~, publish data to ~yolo/debug_node~
'''

class Adaface(Node):
  def __init__(self):
    super().__init__('adaface')
    self.get_logger().info('========================') 
    self.get_logger().info('Start face recognition!')
    self.get_logger().info('========================') 

    self.cv_bridge = CvBridge()
    
     # params
    self.declare_parameter("fr_weight", "ir_50")
    model = self.get_parameter("fr_weight").get_parameter_value().string_value

    self.declare_parameter("device", "cuda:0")
    self.device = self.get_parameter("device").get_parameter_value().string_value

    self.declare_parameter("option", 1)  
    option = self.get_parameter("option").get_parameter_value().integer_value
    
    self.declare_parameter("thresh", 0.2)
    self.thresh = self.get_parameter("thresh").get_parameter_value().double_value

    self.declare_parameter("max_obj", 6)        
    self.max_obj = self.get_parameter("max_obj").get_parameter_value().integer_value

    self.declare_parameter("dataset", "face_dataset/test")  
    self.dataset = self.get_parameter("dataset").get_parameter_value().string_value
    
    self.declare_parameter("video", 0)
    self.video = self.get_parameter("video").get_parameter_value().string_value
    
    self.declare_parameter("image_reliability",
                            QoSReliabilityPolicy.BEST_EFFORT)

    image_qos_profile = QoSProfile(
        reliability=self.get_parameter(
            "image_reliability").get_parameter_value().integer_value,
        history=QoSHistoryPolicy.KEEP_LAST,
        durability=QoSDurabilityPolicy.VOLATILE,
        depth=1
    )

    self._face_cache = {}
    self.adaface = AdaFace(
        model=model,
        option=option,
        dataset=self.dataset,
        video=self.video,
        max_obj=self.max_obj,
        thresh=self.thresh,
    )

    #pubs
    self._adaface_pub = self.create_publisher(DetectionArray, 'adaface_msg',10)

    ## subs
    # 이미지와 message를 subscribe
    tracking_sub = message_filters.Subscriber(
        self, DetectionArray, "detections", qos_profile =10)
    image_sub = message_filters.Subscriber(
        self, Image, "image_raw", qos_profile=image_qos_profile)

    
    # 이미지와 message를 동기화
    self._synchronizer = message_filters.ApproximateTimeSynchronizer(
        (image_sub, tracking_sub), 10, 0.1)
    
    # Adaface_main 부름
    self._synchronizer.registerCallback(self.adaface_main)

  
  def adaface_main(self, img_msg: Image, detections_msg: DetectionArray) -> None:
        
        # convert image for align
        cv_image = self.cv_bridge.imgmsg_to_cv2(img_msg)

        detection : Detection
        # face_detections_msg = DetectionArray()
        # face_detections_msg.header = img_msg.header

        keys_to_keep = []
        for n, detection in enumerate(detections_msg.detections):
          # 객체 이미지 위치 잡고 그걸 inference로 보낸다
          x1 = np.clip(int(detection.bbox.center.position.x - detection.bbox.size.x / 2), 0, img_msg.width) # img_msg.width = 640 # ? 설정 시: 640 - 1
          y1 = np.clip(int(detection.bbox.center.position.y - detection.bbox.size.y / 2), 0, img_msg.height) # img_msg.height = 480
          x2 = np.clip(int(detection.bbox.center.position.x + detection.bbox.size.x / 2), 0, img_msg.width)
          y2 = np.clip(int(detection.bbox.center.position.y + detection.bbox.size.y / 2), 0, img_msg.height)
          
          face_box, face_info = self.adaface.inference(cv_image[y1:y2,x1:x2])

          if face_box:
          # Assume that one person box = one face
            detection.facebox.bbox.center.position.x = float(x1 + (face_box[0][2] + face_box[0][0])//2)
            detection.facebox.bbox.size.x = float(face_box[0][2]- face_box[0][0])
            detection.facebox.bbox.center.position.y = float(y1 + (face_box[0][3] + face_box[0][1])//2)
            detection.facebox.bbox.size.y = float(face_box[0][3]- face_box[0][1])

            # face_detection.id = face_detection.id
            detection.facebox.name = face_info[0]
            detection.facebox.score = face_info[1]
            detection.facebox.isdetect = True            
          else:
             detection.facebox.isdetect = False
             detection.facebox.name = "no face"

          # dictionary 관련 + name update하기
          keys_to_keep.append(detection.id)
            
          if detection.facebox.name not in ["unknown", "no face"]:
              if detection.id not in self._face_cache.keys() or self._face_cache[detection.id] in ["unknown", "no face"]:
                  self._face_cache[detection.id] = detection.facebox.name
              # else: penalty 주자
          else:
              if detection.id not in self._face_cache.keys():
                  self._face_cache[detection.id] = detection.facebox.name
          # 실제 facebox.name을 반영 (dictionary 값을)
          detection.facebox.name = self._face_cache[detection.id]
          detections_msg.detections[n] = detection
        
        self.get_logger().info(f' dict : {self._face_cache}')
        self._adaface_pub.publish(detections_msg)

        keys_to_remove = [key for key in self._face_cache if key not in keys_to_keep]
        # 키 삭제
        for key in keys_to_remove:
            del self._face_cache[key]


def main(args=None): 
  rclpy.init(args=None)
  node = Adaface()
  rclpy.spin(node)
  node.destroy_node()
  rclpy.shutdown()

if __name__ == '__main__':
  main()