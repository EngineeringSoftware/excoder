package org.throwgen.core;

import java.lang.Class;
import java.lang.ClassNotFoundException;

public class ParentFinder {
    public static Class<?> findParentClass(String className) {
        try {
            Class<?> cls = Class.forName(className);
            Class<?> parentClass = cls.getSuperclass();
            return parentClass;
        } catch (ClassNotFoundException e) {
            return null;
        }
    }

    public static void main(String[] args) {
        // Example usage
        String className = args[0];
        Class<?> parentClass = findParentClass(className);
        String parentClassName;
        if (parentClass != null) {
            parentClassName = parentClass.getName();
        } else {
            parentClassName = "null";
        }
        System.out.println("parent_class:" + parentClassName + ";");
    }
}
