/**
 * core/ros.js
 * ROS WebSocket singleton.
 * Uses bundled roslib package first, with optional global fallback.
 * Usage:
 *   import { connectROS, disconnectROS, subscribeROS, publishROS } from './core/ros'
 */

import * as ROSLIB from 'roslib';

let ros = null;
const subscribers = {}; // topic -> ROSLIB.Topic
const listeners = {};   // topic -> Set<callback>

function getROSLib() {
  if (ROSLIB) return ROSLIB;
  if (typeof window !== 'undefined' && window.ROSLIB) return window.ROSLIB;
  throw new Error('ROSLIB is unavailable. Check local bundle/dependency loading state.');
}

// ─── Connect ────────────────────────────────────────────────────────────────
export async function connectROS(url, { onConnect, onError, onClose } = {}) {
  const roslib = getROSLib();
  if (ros) { ros.close(); ros = null; }

  ros = new roslib.Ros({ url });

  ros.on('connection', () => {
    onConnect?.();
    // Re-subscribe any existing listeners
    Object.keys(listeners).forEach(topic => _subscribe(topic));
  });
  ros.on('error',   e => onError?.(e));
  ros.on('close',   () => {
    onClose?.();
    Object.values(subscribers).forEach(s => { try { s.unsubscribe(); } catch { return; } });
    Object.keys(subscribers).forEach(k => delete subscribers[k]);
  });
}

export function disconnectROS() {
  if (!ros) return;
  ros.close();
  ros = null;
}

export function isConnected() {
  return !!ros;
}

// ─── Subscribe ──────────────────────────────────────────────────────────────
/**
 * Subscribe to a ROS topic.
 * @param {string} topic  - ROS topic name
 * @param {string} msgType - e.g. 'std_msgs/String'
 * @param {function} cb   - called with (parsedPayload)
 * @returns {function} unsubscribe function
 */
export function subscribeROS(topic, msgType, cb) {
  if (!listeners[topic]) listeners[topic] = new Set();
  listeners[topic].add(cb);

  if (ros && !subscribers[topic]) _subscribe(topic, msgType);

  return () => {
    listeners[topic]?.delete(cb);
    if (listeners[topic]?.size === 0) {
      subscribers[topic]?.unsubscribe();
      delete subscribers[topic];
      delete listeners[topic];
    }
  };
}

function _subscribe(topic, msgType) {
  if (!ros) return;
  const roslib = getROSLib();
  const type = msgType || _inferMsgType(topic);
  const sub = new roslib.Topic({ ros, name: topic, messageType: type });
  sub.subscribe(msg => {
    const val = msg.data !== undefined ? msg.data : msg;
    listeners[topic]?.forEach(cb => cb(val));
  });
  subscribers[topic] = sub;
}

function _inferMsgType(topic) {
  if (topic.includes('image'))    return 'sensor_msgs/Image';
  if (topic.includes('offset'))   return 'geometry_msgs/Point';
  if (topic.includes('wake_word') || topic.includes('speaking') ||
      topic.includes('done')      || topic.includes('trigger'))
    return 'std_msgs/Bool';
  return 'std_msgs/String';
}

// ─── Publish ─────────────────────────────────────────────────────────────────
export function publishROS(topic, msgType, data) {
  if (!ros) return;
  const roslib = getROSLib();
  const t = new roslib.Topic({ ros, name: topic, messageType: msgType });
  t.publish(new roslib.Message(data));
}
